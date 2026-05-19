FROM mcr.microsoft.com/oss/go/microsoft/golang:1.26-azurelinux3.0 AS builder

WORKDIR /app

RUN tdnf install -y git && tdnf clean all

COPY go.mod ./
COPY go.sum ./
COPY main.go ./

# Download dependencies
RUN go mod download

RUN GOEXPERIMENT=ms_nocgo_opensslcrypto CGO_ENABLED=0 GOOS=linux go build -o /event-processor

FROM mcr.microsoft.com/azurelinux/distroless/base:3.0
WORKDIR /app

COPY --from=builder /event-processor .
USER nobody

CMD ["./event-processor"]