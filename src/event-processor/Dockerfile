FROM golang:1.25-alpine AS builder

WORKDIR /app

RUN apk add --no-cache git

COPY go.mod ./
COPY go.sum ./
COPY main.go ./

# Download dependencies
RUN go mod download

RUN CGO_ENABLED=0 GOOS=linux go build -o /event-processor

FROM alpine:latest
RUN apk --no-cache add ca-certificates
WORKDIR /app

COPY --from=builder /event-processor .
USER nobody

CMD ["./event-processor"]