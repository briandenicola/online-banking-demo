package main

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/Azure/azure-sdk-for-go/sdk/messaging/azeventhubs"
	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/attribute"
	"go.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracehttp"
	"go.opentelemetry.io/otel/sdk/resource"
	sdktrace "go.opentelemetry.io/otel/sdk/trace"
	"go.opentelemetry.io/otel/trace"
)

// EventProcessor handles Event Hub messages
type EventProcessor struct {
	tracer trace.Tracer
	client *azeventhubs.ConsumerClient
}

// Event represents an incoming banking event
type Event struct {
	ID        string                 `json:"id"`
	Timestamp time.Time              `json:"timestamp"`
	Source    string                 `json:"source"`
	Type      string                 `json:"type"`
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
	ctx := context.Background()

	// Get configuration from environment
	eventHubConnStr := os.Getenv("EVENTHUB_CONNECTION_STRING")
	eventHubName := os.Getenv("EVENTHUB_NAME")
	if eventHubName == "" {
		eventHubName = "banking-events"
	}

	// Create consumer client
	consumerClient, err := azeventhubs.NewConsumerClientFromConnectionString(eventHubConnStr, eventHubName, azeventhubs.DefaultConsumerGroup, nil)
	if err != nil {
		log.Fatalf("Failed to create consumer client: %v", err)
	}
	defer consumerClient.Close(ctx)

	processor := &EventProcessor{
		tracer: tracer,
		client: consumerClient,
	}

	// Start processing events
	log.Println("Event processor starting...")

	// Handle graceful shutdown
	sigChan := make(chan os.Signal, 1)
	signal.Notify(sigChan, syscall.SIGINT, syscall.SIGTERM)

	errChan := make(chan error, 1)
	go func() {
		processor.ProcessEvents(ctx)
	}()

	select {
	case <-sigChan:
		log.Println("Shutting down event processor...")
	case err := <-errChan:
		log.Fatalf("Error in event processor: %v", err)
	}
}

// ProcessEvents processes incoming events from Event Hub
func (p *EventProcessor) ProcessEvents(ctx context.Context) {
	partitionProcessor := &azeventhubs.Processor{
		OnProcessEvents: func(ctx context.Context, partitionContext *azeventhubs.ProcessorPartitionContext, events []*azeventhubs.ReceivedEventData) error {
			ctx, span := p.tracer.Start(ctx, "ProcessEvents")
			defer span.End()

			for _, event := range events {
				var evt Event
				if err := json.Unmarshal(event.Body, &evt); err != nil {
					log.Printf("Failed to unmarshal event: %v", err)
					continue
				}

				log.Printf("Processing event: %s from %s", evt.Type, evt.Source)
				span.SetAttributes(
					attribute.String("event.id", evt.ID),
					attribute.String("event.type", evt.Type),
					attribute.String("event.source", evt.Source),
				)

				// Route to appropriate handler based on event type
				p.handleEvent(ctx, &evt)
			}

			return nil
		},
		OnPartitionInitialize: func(ctx context.Context, partitionContext *azeventhubs.ProcessorPartitionContext) error {
			log.Printf("Partition %s initialized", partitionContext.PartitionID)
			return nil
		},
	}

	err := p.client.RunProcessor(ctx, partitionProcessor, nil)
	if err != nil {
		log.Printf("Error running processor: %v", err)
	}
}

// handleEvent routes events to appropriate handlers
func (p *EventProcessor) handleEvent(ctx context.Context, evt *Event) {
	switch evt.Type {
	case "TransactionCreated":
		p.handleTransactionCreated(ctx, evt)
	case "TransferInitiated":
		p.handleTransferInitiated(ctx, evt)
	case "UserRegistered":
		p.handleUserRegistered(ctx, evt)
	default:
		log.Printf("Unknown event type: %s", evt.Type)
	}
}

func (p *EventProcessor) handleTransactionCreated(ctx context.Context, evt *Event) {
	ctx, span := p.tracer.Start(ctx, "handleTransactionCreated")
	defer span.End()

	log.Printf("Transaction created: %+v", evt.Data)
	// TODO: Enrich with account data, update analytics
}

func (p *EventProcessor) handleTransferInitiated(ctx context.Context, evt *Event) {
	ctx, span := p.tracer.Start(ctx, "handleTransferInitiated")
	defer span.End()

	log.Printf("Transfer initiated: %+v", evt.Data)
	// TODO: Track transfer metrics
}

func (p *EventProcessor) handleUserRegistered(ctx context.Context, evt *Event) {
	ctx, span := p.tracer.Start(ctx, "handleUserRegistered")
	defer span.End()

	log.Printf("User registered: %+v", evt.Data)
	// TODO: Initialize user profile, send welcome email
}

func initTracer() (*sdktrace.TracerProvider, error) {
	appInsightsConnStr := os.Getenv("APPLICATIONINSIGHTS_CONNECTION_STRING")
	if appInsightsConnStr == "" {
		// Return a no-op tracer for local development
		return sdktrace.NewTracerProvider(), nil
	}

	// In production, configure OTLP exporter
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
		sdktrace.WithResource(resource.NewWithAttributes(
			"online-banking-demo",
			attribute.String("service.name", "event-processor"),
			attribute.String("deployment.environment", "production"),
		)),
	)

	otel.SetTracerProvider(tp)
	return tp, nil
}