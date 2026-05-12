package main

import (
	"encoding/base64"
	"encoding/json"
	"testing"
)

// TestParseRedisConnectionString verifies connection string parsing for various formats.
func TestParseRedisConnectionString(t *testing.T) {
	tests := []struct {
		name         string
		input        string
		wantAddr     string
		wantPassword string
		wantTLS      bool
	}{
		{
			name:     "host:port only",
			input:    "myredis:6379",
			wantAddr: "myredis:6379",
			wantTLS:  false,
		},
		{
			name:     "host:port with ssl=True",
			input:    "myredis.redis.cache.windows.net:10000,ssl=True",
			wantAddr: "myredis.redis.cache.windows.net:10000",
			wantTLS:  true,
		},
		{
			name:         "host:port with password and ssl",
			input:        "myredis:6380,password=SecretKey123,ssl=True",
			wantAddr:     "myredis:6380",
			wantPassword: "SecretKey123",
			wantTLS:      true,
		},
		{
			name:     "host:port with abortConnect=False",
			input:    "myredis:6379,ssl=True,abortConnect=False",
			wantAddr: "myredis:6379",
			wantTLS:  true,
		},
		{
			name:     "ssl=false (lowercase)",
			input:    "myredis:6379,ssl=false",
			wantAddr: "myredis:6379",
			wantTLS:  false,
		},
		{
			name:     "empty string defaults to redis:6379",
			input:    "",
			wantAddr: "",
			wantTLS:  false,
		},
		{
			name:     "whitespace in segments is trimmed",
			input:    "myredis:6379, ssl = True , password = key123",
			wantAddr: "myredis:6379",
			wantPassword: "key123",
			wantTLS:      true,
		},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			opts := parseRedisConnectionString(tc.input)

			if opts.Addr != tc.wantAddr {
				t.Errorf("Addr = %q, want %q", opts.Addr, tc.wantAddr)
			}
			if opts.Password != tc.wantPassword {
				t.Errorf("Password = %q, want %q", opts.Password, tc.wantPassword)
			}
			if (opts.TLSConfig != nil) != tc.wantTLS {
				t.Errorf("TLS enabled = %v, want %v", opts.TLSConfig != nil, tc.wantTLS)
			}
		})
	}
}

// TestExtractOIDFromToken verifies JWT OID extraction from various token formats.
func TestExtractOIDFromToken(t *testing.T) {
	tests := []struct {
		name    string
		token   string
		wantOID string
	}{
		{
			name:    "valid JWT with oid claim",
			token:   makeTestJWT(map[string]string{"oid": "abc-123-def"}),
			wantOID: "abc-123-def",
		},
		{
			name:    "valid JWT without oid claim",
			token:   makeTestJWT(map[string]string{"sub": "user-1"}),
			wantOID: "",
		},
		{
			name:    "empty token",
			token:   "",
			wantOID: "",
		},
		{
			name:    "malformed token (no dots)",
			token:   "not-a-jwt",
			wantOID: "",
		},
		{
			name:    "token with two parts",
			token:   "header.payload",
			wantOID: "",
		},
		{
			name:    "token with invalid base64 payload",
			token:   "header.!!!invalid!!!.signature",
			wantOID: "",
		},
		{
			name:    "token with non-JSON payload",
			token:   "header." + base64.RawURLEncoding.EncodeToString([]byte("not json")) + ".signature",
			wantOID: "",
		},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			got := extractOIDFromToken(tc.token)
			if got != tc.wantOID {
				t.Errorf("extractOIDFromToken() = %q, want %q", got, tc.wantOID)
			}
		})
	}
}

// TestExtractOIDFromToken_PaddingVariations verifies base64 padding handling.
func TestExtractOIDFromToken_PaddingVariations(t *testing.T) {
	// Create payloads of different lengths to test base64 padding (0, 1, 2, 3 pad chars)
	oids := []string{"a", "ab", "abc", "abcd"}
	for _, oid := range oids {
		t.Run("oid="+oid, func(t *testing.T) {
			token := makeTestJWT(map[string]string{"oid": oid})
			got := extractOIDFromToken(token)
			if got != oid {
				t.Errorf("extractOIDFromToken() = %q, want %q", got, oid)
			}
		})
	}
}

// TestBankingEventParsing verifies JSON deserialization of banking events.
func TestBankingEventParsing(t *testing.T) {
	tests := []struct {
		name      string
		json      string
		wantType  string
		wantError bool
	}{
		{
			name:     "TransactionCreated event",
			json:     `{"eventType":"TransactionCreated","timestamp":"2024-01-01T00:00:00Z","data":{"accountId":"acc-1","amount":100}}`,
			wantType: "TransactionCreated",
		},
		{
			name:     "TransferInitiated event",
			json:     `{"eventType":"TransferInitiated","timestamp":"2024-01-01T00:00:00Z","data":{"fromAccountId":"acc-1","toAccountId":"acc-2","amount":50}}`,
			wantType: "TransferInitiated",
		},
		{
			name:     "unknown event type",
			json:     `{"eventType":"CustomEvent","timestamp":"2024-01-01T00:00:00Z","data":{}}`,
			wantType: "CustomEvent",
		},
		{
			name:      "invalid JSON",
			json:      `{not valid json`,
			wantError: true,
		},
		{
			name:     "empty data map",
			json:     `{"eventType":"Test","timestamp":"2024-01-01T00:00:00Z","data":{}}`,
			wantType: "Test",
		},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			var evt BankingEvent
			err := json.Unmarshal([]byte(tc.json), &evt)

			if tc.wantError {
				if err == nil {
					t.Error("expected error, got nil")
				}
				return
			}

			if err != nil {
				t.Fatalf("unexpected error: %v", err)
			}
			if evt.EventType != tc.wantType {
				t.Errorf("EventType = %q, want %q", evt.EventType, tc.wantType)
			}
		})
	}
}

// makeTestJWT creates a minimal JWT token with the given claims for testing.
func makeTestJWT(claims map[string]string) string {
	header := base64.RawURLEncoding.EncodeToString([]byte(`{"alg":"none","typ":"JWT"}`))
	claimsJSON, _ := json.Marshal(claims)
	payload := base64.RawURLEncoding.EncodeToString(claimsJSON)
	return header + "." + payload + ".signature"
}
