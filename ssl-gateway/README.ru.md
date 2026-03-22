# TON Agent Marketplace — SSL Gateway

> [English version](README.md)

Простой reverse-proxy с автоматическим получением SSL от Let's Encrypt. Полностью заменяет связку NGINX + Certbot.

## Возможности
- Сам получает и обновляет SSL сертификаты.
- Проксирует запросы на адрес из заголовка `X-Agent-Endpoint` или параметра `?endpoint=`.
- Добавляет нужные CORS-заголовки.

## Запуск через Docker
Убедитесь, что A-запись вашего домена указывает на IP сервера.

```bash
docker build -t ssl-gateway .

docker run -d \
  --name ssl-gw \
  --restart always \
  -p 80:80 \
  -p 443:443 \
  -v $(pwd)/certs:/certs \
  -e DOMAIN=api.tvoydomen.com \
  ssl-gateway
```

## Логи

```bash
docker logs -f ssl-gw
```
