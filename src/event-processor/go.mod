module event-processor

go 1.22

require (
	github.com/Azure/azure-sdk-for-go/sdk/messaging/azeventhubs v1.0.0
	github.com/Azure/azure-sdk-for-go/sdk/storage/azblob v1.0.0
	go.opentelemetry.io/otel v1.26.0
	go.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracehttp v1.26.0
	go.opentelemetry.io/otel/sdk/resource v1.26.0
	go.opentelemetry.io/otel/sdk/trace v1.26.0
)