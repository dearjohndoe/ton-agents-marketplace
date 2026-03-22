FROM golang:1.22-alpine AS build
WORKDIR /app
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 go build -o ssl-gateway .

FROM alpine:3.20
RUN apk add --no-cache ca-certificates
COPY --from=build /app/ssl-gateway /ssl-gateway
EXPOSE 443 80
ENTRYPOINT ["/ssl-gateway"]
