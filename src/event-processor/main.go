package main

import (
	"context"
	"crypto/tls"
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"os"
	"os/signal"
	"strings"
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
	consumerGroup = "event-processor-group"
	consumerName  = "event-processor-1"
	// Azure Cache for Redis scope for Entra ID token requests
	redisCacheScope = "acca5fbb-b7e4-4009-81f1-37e38fd66d78/.default"
)

// EventProcessor handles Redis Stream messages
type EventProcessor struct {
	tracer trace.Tracer
	client *redis.Client
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

	// Verify Redis connectivity with retry
	for i := 0; i < 10; i++ {
		if err := rdb.Ping(ctx).Err(); err == nil {
			log.Println("✅ Redis connectivity verified")
			break
		} else if i == 9 {
			log.Fatalf("Failed to connect to Redis after retries: %v", err)
		} else {
			log.Printf("Redis not ready, retrying in %ds...", i+1)
			time.Sleep(time.Duration(i+1) * time.Second)
		}
	}
	defer rdb.Close()

	// Create consumer group (idempotent)
	err = rdb.XGroupCreateMkStream(ctx, streamName, consumerGroup, "0").Err()
	if err != nil && err.Error() != "BUSYGROUP Consumer Group name already exists" {
		log.Fatalf("Failed to create consumer group: %v", err)
	}
	log.Printf("Consumer group '%s' ready on stream '%s'", consumerGroup, streamName)

	processor := &EventProcessor{
		tracer: tracer,
		client: rdb,
	}

	// Handle graceful shutdown
	sigChan := make(chan os.Signal, 1)
	signal.Notify(sigChan, syscall.SIGINT, syscall.SIGTERM)

	go processor.consumeEvents(ctx)

	// Start health probe HTTP server
	go func() {
		mux := http.NewServeMux()
		mux.HandleFunc("/healthz", func(w http.ResponseWriter, r *http.Request) {
			w.Header().Set("Content-Type", "application/json")
			fmt.Fprintf(w, `{"status":"healthy","service":"event-processor","timestamp":"%s"}`, time.Now().UTC().Format(time.RFC3339))
		})
		mux.HandleFunc("/readyz", func(w http.ResponseWriter, r *http.Request) {
			w.Header().Set("Content-Type", "application/json")
			fmt.Fprint(w, `{"status":"ready"}`)
		})
		log.Println("Health probe server listening on :8080")
		if err := http.ListenAndServe(":8080", mux); err != nil {
			log.Printf("Health server error: %v", err)
		}
	}()

	log.Println("Event processor started — consuming from Redis Stream")

	<-sigChan
	log.Println("Shutting down event processor...")
	cancel()
}

// newRedisClient creates a Redis client. If AZURE_CLIENT_ID is set (workload identity),
// it uses Entra ID token-based auth. Otherwise falls back to connection string parsing
// (for local dev with docker-compose).
func newRedisClient(ctx context.Context, connStr string) (*redis.Client, error) {
	opts := parseRedisConnectionString(connStr)

	// If running with Azure workload identity, use Entra ID token auth
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

		opts.Password = token.Token
		log.Println("Using Entra ID token for Redis authentication")

		client := redis.NewClient(opts)

		// Refresh token periodically (Azure tokens expire in ~1 hour)
		go refreshRedisToken(ctx, client, cred)

		return client, nil
	}

	log.Println("Using connection string for Redis authentication (local dev)")
	return redis.NewClient(opts), nil
}

// refreshRedisToken periodically refreshes the Entra ID token on the Redis connection
func refreshRedisToken(ctx context.Context, client *redis.Client, cred *azidentity.DefaultAzureCredential) {
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
			if err := client.Do(ctx, "AUTH", "default", token.Token).Err(); err != nil {
				log.Printf("⚠️ Failed to re-auth Redis with new token: %v", err)
			} else {
				log.Println("✅ Redis token refreshed")
			}
		}
	}
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
			Block:    5 * time.Second,
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
			time.Sleep(backoff)
			if backoff < 30*time.Second {
				backoff *= 2
			}
			continue
		}

		backoff = time.Second

		for _, stream := range streams {
			for _, message := range stream.Messages {
				p.processMessage(ctx, message)

				// Acknowledge the message
				if err := p.client.XAck(ctx, streamName, consumerGroup, message.ID).Err(); err != nil {
					log.Printf("Failed to ACK message %s: %v", message.ID, err)
				}
			}
		}
	}
}

func (p *EventProcessor) processMessage(ctx context.Context, message redis.XMessage) {
	ctx, span := p.tracer.Start(ctx, "processMessage")
	defer span.End()

	payloadStr, ok := message.Values["payload"].(string)
	if !ok {
		log.Printf("Message %s has no payload field", message.ID)
		return
	}

	var evt BankingEvent
	if err := json.Unmarshal([]byte(payloadStr), &evt); err != nil {
		log.Printf("Failed to unmarshal event %s: %v", message.ID, err)
		return
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