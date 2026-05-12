package main

import (
	"context"
	"crypto/tls"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"os"
	"os/signal"
	"strconv"
	"strings"
	"sync"
	"syscall"
	"time"

	"github.com/Azure/azure-sdk-for-go/sdk/azcore/policy"
	"github.com/Azure/azure-sdk-for-go/sdk/azidentity"
	"github.com/redis/go-redis/v9"
	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/attribute"
	"go.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracehttp"
	sdkresource "go.opentelemetry.io/otel/sdk/resource"
	sdktrace "go.opentelemetry.io/otel/sdk/trace"
	"go.opentelemetry.io/otel/trace"
)

const (
	streamName    = "banking-events"
	dlqStreamName = "banking-events-dlq"
	consumerGroup = "event-processor-group"
	consumerName  = "event-processor-1"
	// Azure Cache for Redis scope for Entra ID token requests
	redisCacheScope = "acca5fbb-b7e4-4009-81f1-37e38fd66d78/.default"
)

// EventProcessor handles Redis Stream messages
type EventProcessor struct {
	tracer       trace.Tracer
	client       redis.Cmdable
	redisReady   bool
	wg           sync.WaitGroup
	maxRetries   int
	failureCounts map[string]int
	mu           sync.Mutex
}

// BankingEvent represents an incoming banking event
type BankingEvent struct {
	EventType string                 `json:"eventType"`
	Timestamp string                 `json:"timestamp"`
	Data      map[string]interface{} `json:"data"`
}

func main() {
	// Initialize OpenTelemetry
	tp, err := initTracer()
	if err != nil {
		log.Fatalf("Failed to initialize tracer: %v", err)
	}
	defer func() {
		ctx, cancel := context.WithTimeout(context.Background(), time.Second*5)
		defer cancel()
		_ = tp.Shutdown(ctx)
	}()

	tracer := otel.Tracer("event-processor")
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	// Get Redis connection from environment
	// Format: host:port,ssl=True,abortConnect=False (no password — Entra ID auth)
	redisConnStr := os.Getenv("REDIS__CONNECTIONSTRING")
	if redisConnStr == "" {
		redisConnStr = "redis:6379"
	}

	rdb, err := newRedisClient(ctx, redisConnStr)
	if err != nil {
		log.Fatalf("Failed to create Redis client: %v", err)
	}
	defer func() {
		if c, ok := rdb.(interface{ Close() error }); ok {
			c.Close()
		}
	}()

	maxRetries := 3
	if v := os.Getenv("DLQ_MAX_RETRIES"); v != "" {
		if n, err := strconv.Atoi(v); err == nil && n > 0 {
			maxRetries = n
		}
	}

	processor := &EventProcessor{
		tracer:        tracer,
		client:        rdb,
		maxRetries:    maxRetries,
		failureCounts: make(map[string]int),
	}

	// Handle graceful shutdown
	sigChan := make(chan os.Signal, 1)
	signal.Notify(sigChan, syscall.SIGINT, syscall.SIGTERM)

	// Start health probe HTTP server BEFORE Redis connectivity check
	// so that probes can report status while Redis is connecting
	go func() {
		mux := http.NewServeMux()
		mux.HandleFunc("/healthz", func(w http.ResponseWriter, r *http.Request) {
			w.Header().Set("Content-Type", "application/json")
			fmt.Fprintf(w, `{"status":"healthy","service":"event-processor","timestamp":"%s"}`, time.Now().UTC().Format(time.RFC3339))
		})
		mux.HandleFunc("/readyz", func(w http.ResponseWriter, r *http.Request) {
			w.Header().Set("Content-Type", "application/json")
			if processor.redisReady {
				fmt.Fprint(w, `{"status":"ready"}`)
			} else {
				w.WriteHeader(http.StatusServiceUnavailable)
				fmt.Fprint(w, `{"status":"not_ready","reason":"redis_connecting"}`)
			}
		})
		log.Println("Health probe server listening on :8080")
		if err := http.ListenAndServe(":8080", mux); err != nil {
			log.Printf("Health server error: %v", err)
		}
	}()

	// Verify Redis connectivity with retry (no fatal on failure — keep trying)
	for i := 0; ; i++ {
		if err := rdb.Ping(ctx).Err(); err == nil {
			log.Println("✅ Redis connectivity verified")
			processor.redisReady = true
			break
		} else {
			backoff := time.Duration(i+1) * time.Second
			if backoff > 30*time.Second {
				backoff = 30 * time.Second
			}
			log.Printf("Redis not ready (attempt %d): %v — retrying in %v...", i+1, err, backoff)
			select {
			case <-ctx.Done():
				log.Println("Context cancelled during Redis startup retry")
				return
			case <-time.After(backoff):
			}
		}
	}

	// Create consumer group (idempotent)
	err = rdb.XGroupCreateMkStream(ctx, streamName, consumerGroup, "0").Err()
	if err != nil && err.Error() != "BUSYGROUP Consumer Group name already exists" {
		log.Fatalf("Failed to create consumer group: %v", err)
	}
	log.Printf("Consumer group '%s' ready on stream '%s'", consumerGroup, streamName)

	go processor.consumeEvents(ctx)

	log.Println("Event processor started — consuming from Redis Stream")

	<-sigChan
	log.Println("Shutting down event processor — draining in-flight messages...")
	cancel()
	processor.wg.Wait()
	log.Println("All in-flight messages drained. Shutdown complete.")
}

// newRedisClient creates a Redis client. If AZURE_CLIENT_ID is set (workload identity),
// it uses a ClusterClient with Entra ID token-based auth (Azure Managed Redis uses OSS
// Cluster mode). Otherwise falls back to standard Client with connection string parsing
// (for local dev with docker-compose).
func newRedisClient(ctx context.Context, connStr string) (redis.Cmdable, error) {
	opts := parseRedisConnectionString(connStr)

	// If running with Azure workload identity, use ClusterClient + Entra ID token auth
	if os.Getenv("AZURE_CLIENT_ID") != "" {
		cred, err := azidentity.NewDefaultAzureCredential(nil)
		if err != nil {
			return nil, fmt.Errorf("failed to create Azure credential: %w", err)
		}

		token, err := cred.GetToken(ctx, policy.TokenRequestOptions{
			Scopes: []string{redisCacheScope},
		})
		if err != nil {
			return nil, fmt.Errorf("failed to get Redis token: %w", err)
		}

		oid := extractOIDFromToken(token.Token)
		log.Printf("Using Entra ID token for Redis ClusterClient (OID: %s)", oid)

		clusterOpts := &redis.ClusterOptions{
			Addrs:    []string{opts.Addr},
			Username: oid,
			Password: token.Token,
		}
		if opts.TLSConfig != nil {
			// Extract hostname from address for TLS ServerName verification
			redisHost := opts.Addr
			if idx := strings.LastIndex(redisHost, ":"); idx > 0 {
				redisHost = redisHost[:idx]
			}
			clusterOpts.TLSConfig = &tls.Config{
				MinVersion: tls.VersionTLS12,
				ServerName: redisHost,
			}
		}

		client := redis.NewClusterClient(clusterOpts)

		// Refresh token periodically (Azure tokens expire in ~1 hour)
		go refreshRedisToken(ctx, client, cred)

		return client, nil
	}

	log.Println("Using connection string for Redis authentication (local dev)")
	return redis.NewClient(opts), nil
}

// refreshRedisToken periodically refreshes the Entra ID token on the Redis connection
func refreshRedisToken(ctx context.Context, client *redis.ClusterClient, cred *azidentity.DefaultAzureCredential) {
	for {
		select {
		case <-ctx.Done():
			return
		case <-time.After(45 * time.Minute):
			token, err := cred.GetToken(ctx, policy.TokenRequestOptions{
				Scopes: []string{redisCacheScope},
			})
			if err != nil {
				log.Printf("⚠️ Failed to refresh Redis token: %v", err)
				continue
			}
			oid := extractOIDFromToken(token.Token)
			if err := client.ForEachShard(ctx, func(ctx context.Context, shard *redis.Client) error {
				return shard.Do(ctx, "AUTH", oid, token.Token).Err()
			}); err != nil {
				log.Printf("⚠️ Failed to re-auth Redis with new token: %v", err)
			} else {
				log.Println("✅ Redis token refreshed")
			}
		}
	}
}

// extractOIDFromToken extracts the Object ID (oid claim) from a JWT access token
func extractOIDFromToken(token string) string {
	parts := strings.Split(token, ".")
	if len(parts) != 3 {
		return ""
	}
	// Decode the payload (second part), adding padding if needed
	payload := parts[1]
	if m := len(payload) % 4; m != 0 {
		payload += strings.Repeat("=", 4-m)
	}
	decoded, err := base64.URLEncoding.DecodeString(payload)
	if err != nil {
		log.Printf("Failed to decode token payload: %v", err)
		return ""
	}
	var claims struct {
		OID string `json:"oid"`
	}
	if err := json.Unmarshal(decoded, &claims); err != nil {
		log.Printf("Failed to parse token claims: %v", err)
		return ""
	}
	return claims.OID
}

// consumeEvents reads from the Redis Stream using consumer groups
func (p *EventProcessor) consumeEvents(ctx context.Context) {
	backoff := time.Second

	for {
		select {
		case <-ctx.Done():
			return
		default:
		}

		streams, err := p.client.XReadGroup(ctx, &redis.XReadGroupArgs{
			Group:    consumerGroup,
			Consumer: consumerName,
			Streams:  []string{streamName, ">"},
			Count:    10,
			Block:    1 * time.Second,
		}).Result()

		if err != nil {
			if err == redis.Nil {
				backoff = time.Second
				continue
			}
			if ctx.Err() != nil {
				return
			}
			log.Printf("Error reading from stream: %v. Retrying in %v...", err, backoff)
			select {
			case <-ctx.Done():
				return
			case <-time.After(backoff):
			}
			if backoff < 30*time.Second {
				backoff *= 2
			}
			continue
		}

		backoff = time.Second

		for _, stream := range streams {
			for _, message := range stream.Messages {
				p.wg.Add(1)
				func(msg redis.XMessage) {
					defer p.wg.Done()

					if err := p.processMessage(ctx, msg); err != nil {
						p.mu.Lock()
						p.failureCounts[msg.ID]++
						count := p.failureCounts[msg.ID]
						p.mu.Unlock()

						log.Printf("Error processing message %s (attempt %d/%d): %v",
							msg.ID, count, p.maxRetries, err)

						if count >= p.maxRetries {
							// Dead-letter: move to DLQ stream, then ACK original
							dlqFields := make(map[string]interface{})
							for k, v := range msg.Values {
								dlqFields[k] = v
							}
							dlqFields["original_id"] = msg.ID
							dlqFields["error"] = fmt.Sprintf("%.500s", err.Error())
							dlqFields["attempts"] = fmt.Sprintf("%d", count)

							if dlqErr := p.client.XAdd(ctx, &redis.XAddArgs{
								Stream: dlqStreamName,
								Values: dlqFields,
							}).Err(); dlqErr != nil {
								log.Printf("Failed to move %s to DLQ: %v", msg.ID, dlqErr)
								return
							}
							if ackErr := p.client.XAck(ctx, streamName, consumerGroup, msg.ID).Err(); ackErr != nil {
								log.Printf("Failed to ACK dead-lettered message %s: %v", msg.ID, ackErr)
							}
							p.mu.Lock()
							delete(p.failureCounts, msg.ID)
							p.mu.Unlock()
							log.Printf("Message %s moved to DLQ after %d failed attempts", msg.ID, count)
						}
						// Do NOT ACK — message stays in pending list for retry
						return
					}

					// ACK only after successful processing
					if err := p.client.XAck(ctx, streamName, consumerGroup, msg.ID).Err(); err != nil {
						log.Printf("Failed to ACK message %s: %v", msg.ID, err)
					}
					p.mu.Lock()
					delete(p.failureCounts, msg.ID)
					p.mu.Unlock()
				}(message)
			}
		}
	}
}

func (p *EventProcessor) processMessage(ctx context.Context, message redis.XMessage) error {
	ctx, span := p.tracer.Start(ctx, "processMessage")
	defer span.End()

	payloadStr, ok := message.Values["payload"].(string)
	if !ok {
		return fmt.Errorf("message %s has no payload field", message.ID)
	}

	var evt BankingEvent
	if err := json.Unmarshal([]byte(payloadStr), &evt); err != nil {
		return fmt.Errorf("failed to unmarshal event %s: %w", message.ID, err)
	}

	span.SetAttributes(
		attribute.String("event.type", evt.EventType),
		attribute.String("event.timestamp", evt.Timestamp),
		attribute.String("message.id", message.ID),
	)

	switch evt.EventType {
	case "TransactionCreated":
		log.Printf("[AUDIT] TransactionCreated: account=%v amount=%v type=%v",
			evt.Data["accountId"], evt.Data["amount"], evt.Data["type"])
	case "TransferInitiated":
		log.Printf("[AUDIT] TransferInitiated: from=%v to=%v amount=%v",
			evt.Data["fromAccountId"], evt.Data["toAccountId"], evt.Data["amount"])
	default:
		log.Printf("[AUDIT] Unknown event type: %s — data: %+v", evt.EventType, evt.Data)
	}

	return nil
}

// parseRedisConnectionString parses a StackExchange.Redis-style connection string
// Format: host:port,ssl=True,abortConnect=False,password=KEY
func parseRedisConnectionString(connStr string) *redis.Options {
	opts := &redis.Options{
		Addr: "redis:6379",
	}

	parts := strings.Split(connStr, ",")
	for i, part := range parts {
		part = strings.TrimSpace(part)
		if i == 0 {
			// First segment is host:port
			opts.Addr = part
			continue
		}
		kv := strings.SplitN(part, "=", 2)
		if len(kv) != 2 {
			continue
		}
		key := strings.ToLower(strings.TrimSpace(kv[0]))
		value := strings.TrimSpace(kv[1])
		switch key {
		case "password":
			opts.Password = value
		case "ssl":
			if strings.EqualFold(value, "true") {
				opts.TLSConfig = &tls.Config{
					MinVersion: tls.VersionTLS12,
				}
			}
		}
	}
	return opts
}

func initTracer() (*sdktrace.TracerProvider, error) {
	appInsightsConnStr := os.Getenv("APPLICATIONINSIGHTS_CONNECTION_STRING")
	if appInsightsConnStr == "" {
		return sdktrace.NewTracerProvider(), nil
	}

	exporter, err := otlptracehttp.New(context.Background(),
		otlptracehttp.WithEndpoint("dc.services.visualstudio.com:443"),
		otlptracehttp.WithHeaders(map[string]string{
			"Authorization": fmt.Sprintf("InstrumentationKey=%s", os.Getenv("APPINSIGHTS_INSTRUMENTATIONKEY")),
		}),
	)
	if err != nil {
		return nil, err
	}

	tp := sdktrace.NewTracerProvider(
		sdktrace.WithBatcher(exporter),
		sdktrace.WithResource(sdkresource.NewWithAttributes(
			"online-banking-demo",
			attribute.String("service.name", "event-processor"),
			attribute.String("deployment.environment", "production"),
		)),
	)

	otel.SetTracerProvider(tp)
	return tp, nil
}