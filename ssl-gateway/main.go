package main

import (
	"context"
	"fmt"
	"log"
	"net"
	"net/http"
	"net/http/httputil"
	"net/url"
	"os"
	"strconv"
	"strings"
	"time"

	"golang.org/x/crypto/acme/autocert"
)

func main() {
	domain := os.Getenv("DOMAIN")
	listen := os.Getenv("LISTEN")

	mux := http.NewServeMux()
	mux.HandleFunc("/health", healthHandler)
	mux.HandleFunc("/", proxyHandler)
	handler := corsMiddleware(mux)

	if domain != "" {
		m := &autocert.Manager{
			Cache:      autocert.DirCache("certs"),
			Prompt:     autocert.AcceptTOS,
			HostPolicy: autocert.HostWhitelist(domain),
		}
		srv := &http.Server{
			Handler:   handler,
			TLSConfig: m.TLSConfig(),
		}
		go http.ListenAndServe(":80", m.HTTPHandler(nil))
		log.Printf("ssl-gateway listening on https://%s", domain)
		log.Fatal(srv.ListenAndServeTLS("", ""))
	} else {
		if listen == "" {
			listen = ":8080"
		}
		log.Printf("ssl-gateway listening on %s (no TLS)", listen)
		log.Fatal(http.ListenAndServe(listen, handler))
	}
}

func healthHandler(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	w.Write([]byte(`{"status":"ok"}`))
}

// CORS headers set by the gateway — stripped from upstream responses to avoid duplication.
var corsHeaders = map[string]bool{
	"Access-Control-Allow-Origin":      true,
	"Access-Control-Allow-Methods":     true,
	"Access-Control-Allow-Headers":     true,
	"Access-Control-Allow-Credentials": true,
	"Access-Control-Expose-Headers":    true,
	"Access-Control-Max-Age":           true,
}

func corsMiddleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Access-Control-Allow-Origin", "*")
		w.Header().Set("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
		w.Header().Set("Access-Control-Allow-Headers", "*")
		w.Header().Set("Access-Control-Expose-Headers", "*")
		if r.Method == "OPTIONS" {
			w.WriteHeader(http.StatusNoContent)
			return
		}
		next.ServeHTTP(w, r)
	})
}

// safeDialer resolves DNS and checks ALL IPs against private ranges
// before establishing a connection — prevents DNS rebinding attacks.
var safeDialer = &net.Dialer{Timeout: 10 * time.Second}

func safeDialContext(ctx context.Context, network, addr string) (net.Conn, error) {
	host, port, err := net.SplitHostPort(addr)
	if err != nil {
		return nil, err
	}

	ips, err := net.DefaultResolver.LookupIPAddr(ctx, host)
	if err != nil {
		return nil, err
	}

	for _, ip := range ips {
		if ip.IP.IsLoopback() || ip.IP.IsPrivate() || ip.IP.IsLinkLocalUnicast() || ip.IP.IsUnspecified() {
			return nil, fmt.Errorf("private address %s not allowed", ip.IP)
		}
	}

	// Connect to the first resolved IP explicitly (so the runtime can't pick a different one)
	return safeDialer.DialContext(ctx, network, net.JoinHostPort(ips[0].IP.String(), port))
}

func getTimeout() time.Duration {
	if s := os.Getenv("TIMEOUT"); s != "" {
		if sec, err := strconv.Atoi(s); err == nil {
			return time.Duration(sec) * time.Second
		}
	}
	return 120 * time.Second
}

var transport = &http.Transport{
	DialContext:           safeDialContext,
	ResponseHeaderTimeout: getTimeout(),
	MaxIdleConns:          100,
	IdleConnTimeout:       90 * time.Second,
}

func proxyHandler(w http.ResponseWriter, r *http.Request) {
	endpoint := r.Header.Get("X-Agent-Endpoint")
	if endpoint == "" {
		endpoint = r.URL.Query().Get("endpoint")
	}
	if endpoint == "" {
		http.Error(w, `{"error":"missing X-Agent-Endpoint header or ?endpoint= param"}`, http.StatusBadRequest)
		return
	}

	targetURL, err := url.Parse(endpoint)
	if err != nil || targetURL.Host == "" {
		http.Error(w, `{"error":"invalid endpoint URL"}`, http.StatusBadRequest)
		return
	}

	// Build final path: endpoint base + request path
	targetURL.Path = joinPath(targetURL.Path, r.URL.Path)
	q := r.URL.Query()
	q.Del("endpoint")
	targetURL.RawQuery = q.Encode()

	proxy := &httputil.ReverseProxy{
		Director: func(req *http.Request) {
			req.URL = targetURL
			req.Host = targetURL.Host

			// Remove gateway-specific header
			req.Header.Del("X-Agent-Endpoint")
		},
		Transport: transport,
		ModifyResponse: func(resp *http.Response) error {
			// Strip upstream CORS headers — gateway sets its own
			for h := range corsHeaders {
				resp.Header.Del(h)
			}
			return nil
		},
		ErrorHandler: func(w http.ResponseWriter, r *http.Request, err error) {
			log.Printf("upstream error: %s %s -> %v", r.Method, targetURL.String(), err)
			http.Error(w, `{"error":"upstream unreachable"}`, http.StatusBadGateway)
		},
	}

	proxy.ServeHTTP(w, r)
}

func joinPath(base, extra string) string {
	a := strings.HasSuffix(base, "/")
	b := strings.HasPrefix(extra, "/")
	switch {
	case a && b:
		return base + extra[1:]
	case !a && !b:
		return base + "/" + extra
	}
	return base + extra
}
