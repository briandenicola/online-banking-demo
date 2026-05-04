FROM golang:1.22-alpine AS builder

WORKDIR /app

# Install git for go modules
RUN apk add --no-cache git

# Copy go.mod and main.go for go mod tidy to work
COPY ./src/event-processor/go.mod ./
COPY ./src/event-processor/main.go ./

# Download dependencies
RUN go mod tidy
RUN go mod download

RUN CGO_ENABLED=0 GOOS=linux go build -o /event-processor

FROM alpine:latest
RUN apk --no-cache add ca-certificates
WORKDIR /root/

COPY --from=builder /event-processor .

EXPOSE 9001

CMD ["./event-processor"]