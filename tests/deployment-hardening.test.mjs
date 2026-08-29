import test from "node:test";
import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

const read = (path) => readFileSync(resolve(path), "utf8");

const cloudflareNetworks = [
  "173.245.48.0/20",
  "103.21.244.0/22",
  "103.22.200.0/22",
  "103.31.4.0/22",
  "141.101.64.0/18",
  "108.162.192.0/18",
  "190.93.240.0/20",
  "188.114.96.0/20",
  "197.234.240.0/22",
  "198.41.128.0/17",
  "162.158.0.0/15",
  "104.16.0.0/13",
  "104.24.0.0/14",
  "172.64.0.0/13",
  "131.0.72.0/22",
  "2400:cb00::/32",
  "2606:4700::/32",
  "2803:f800::/32",
  "2405:b500::/32",
  "2405:8100::/32",
  "2a06:98c0::/29",
  "2c0f:f248::/32",
];

function firstServerBlock(source) {
  const start = source.indexOf("server");
  const open = source.indexOf("{", start);
  let depth = 0;
  for (let index = open; index < source.length; index += 1) {
    if (source[index] === "{") depth += 1;
    if (source[index] === "}" && --depth === 0) return source.slice(start, index + 1);
  }
  throw new Error("unterminated server block");
}

test("Nginx declares and applies buyer edge rate limiting", () => {
  const zonePath = "deploy/redeem-rate-limit.conf";
  assert.equal(existsSync(resolve(zonePath)), true, `${zonePath} is missing`);
  const zone = read(zonePath);
  const keyVhost = read("deploy/buyer.example.com.secure.conf");

  assert.match(zone, /limit_req_zone \$binary_remote_addr zone=redeem_per_ip:10m rate=10r\/m;/);
  assert.match(keyVhost, /location = \/api\/redeem/);
  assert.match(keyVhost, /limit_req zone=redeem_per_ip burst=5 nodelay;/);
  assert.match(keyVhost, /limit_req_status 429;/);
});

test("Nginx trusts only Cloudflare networks when restoring visitor IPs", () => {
  const source = read("deploy/redeem-rate-limit.conf");
  const trustedNetworks = [...source.matchAll(/^set_real_ip_from\s+([^;]+);$/gm)]
    .map((match) => match[1]);

  assert.deepEqual(trustedNetworks, cloudflareNetworks);
  assert.match(source, /^real_ip_header CF-Connecting-IP;$/m);
  assert.match(source, /^real_ip_recursive on;$/m);
  assert.doesNotMatch(source, /^set_real_ip_from\s+(?:0\.0\.0\.0\/0|::\/0);$/m);
});

test("Nginx rate limits the exact admin login endpoint", () => {
  const zones = read("deploy/redeem-rate-limit.conf");
  const saleVhost = read("deploy/admin.example.com.secure.conf");
  const login = saleVhost.match(/location = \/api\/admin\/login\s*\{([^}]*)\}/s)?.[1] || "";

  assert.match(zones, /limit_req_zone \$binary_remote_addr zone=admin_login_per_ip:10m rate=5r\/m;/);
  assert.notEqual(login, "", "sale vhost must define an exact admin login location");
  assert.match(login, /client_max_body_size 4k;/);
  assert.match(login, /limit_req zone=admin_login_per_ip burst=5 nodelay;/);
  assert.match(login, /limit_req_status 429;/);
  assert.match(login, /proxy_pass http:\/\/127\.0\.0\.1:5230;/);
  for (const header of [
    "Host $host",
    "X-Real-IP $remote_addr",
    "X-Forwarded-For $proxy_add_x_forwarded_for",
    "X-Forwarded-Proto $scheme",
    "X-Forwarded-Host $host",
  ]) assert.ok(login.includes(`proxy_set_header ${header};`), `missing ${header}`);
  assert.match(login, /proxy_connect_timeout 30s;/);
  assert.match(login, /proxy_send_timeout 120s;/);
  assert.match(login, /proxy_read_timeout 120s;/);
});

test("default vhosts reject unknown HTTP hosts and TLS SNI", () => {
  const path = "deploy/default-deny.conf";
  assert.equal(existsSync(resolve(path)), true, `${path} is missing`);
  const source = read(path);

  assert.match(source, /listen 80 default_server;/);
  assert.match(source, /listen \[::\]:80 default_server;/);
  assert.match(source, /return 444;/);
  assert.match(source, /listen 443 ssl default_server;/);
  assert.match(source, /listen \[::\]:443 ssl default_server;/);
  assert.match(source, /ssl_reject_handshake on;/);
});

test("deployment installs the default vhost before BaoTa site configs", () => {
  const readme = read("README.md");

  assert.match(readme, /deploy\/default-deny\.conf/);
  assert.match(readme, /0\.default\.conf/);
  assert.match(readme, /0\.default\.conf[\s\S]*(?:默认拒绝站|默认站点)[\s\S]*(?:之前|优先|最先)加载/);
});

test("buyer TLS allows only forward-secret AEAD suites", () => {
  const source = read("deploy/buyer.example.com.secure.conf");
  const cipherLine = source.match(/ssl_ciphers\s+([^;]+);/)?.[1] || "";

  assert.match(source, /ssl_protocols TLSv1\.2 TLSv1\.3;/);
  assert.match(cipherLine, /ECDHE-RSA-AES128-GCM-SHA256/);
  assert.match(cipherLine, /ECDHE-RSA-CHACHA20-POLY1305/);
  assert.doesNotMatch(cipherLine, /RSA\+AES|AES128-SHA|AES256-SHA|CBC/);
});

test("buyer response policy is tight and duplicate upstream headers are hidden", () => {
  const source = read("deploy/buyer.example.com.secure.conf");

  assert.match(source, /default-src 'none'/);
  assert.match(source, /script-src 'self' https:\/\/challenges\.cloudflare\.com/);
  assert.match(source, /frame-src https:\/\/challenges\.cloudflare\.com/);
  assert.match(source, /add_header Cross-Origin-Opener-Policy "same-origin" always;/);
  assert.match(source, /add_header Cross-Origin-Resource-Policy "same-origin" always;/);
  assert.match(source, /proxy_hide_header Content-Security-Policy;/);
  assert.match(source, /proxy_hide_header Strict-Transport-Security;/);
});

test("deployment documents Redis guard defaults and patched dependencies", () => {
  const env = read("deploy/key-sale-system.env.example");
  const requirements = read("requirements.txt");
  const readme = read("README.md");

  for (const setting of [
    "REDIS_URL=redis://127.0.0.1:6379/0",
    "REDEEM_CONCURRENCY=10",
    "REDEEM_PREPARE_TIMEOUT_SECONDS=180",
    "REDEEM_LEASE_SECONDS=210",
    "REDEEM_FAILURE_THRESHOLD=5",
  ]) assert.match(env, new RegExp(setting.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
  assert.match(requirements, /^cryptography==48\.0\.1$/m);
  assert.match(requirements, /^redis==7\.0\.1$/m);
  assert.match(readme, /redeem-rate-limit\.conf/);
  assert.match(readme, /0\.redeem-rate-limit\.conf/);
  assert.doesNotMatch(readme, /\/etc\/nginx\/conf\.d/);
  assert.match(read("deploy/redeem-rate-limit.conf"), /0\.redeem-rate-limit\.conf/);
});

test("HTTP vhosts preserve ACME handling and redirect to canonical hosts", () => {
  for (const host of ["buyer.example.com", "admin.example.com"]) {
    const http = firstServerBlock(read(`deploy/${host}.secure.conf`));
    const includeAt = http.indexOf(`well-known/${host}.conf`);
    const fallbackAt = http.indexOf("location /");

    assert.ok(includeAt >= 0, `${host} must preserve the panel ACME include`);
    assert.ok(fallbackAt > includeAt, `${host} ACME include must precede the redirect fallback`);
    assert.match(http, new RegExp(`if \\(\\$host != ${host.replaceAll(".", "\\.")}\\)\\s*\\{[^}]*return 444;`, "s"));
    assert.match(http, new RegExp(`location \/\\s*\\{[^}]*return 301 https:\\/\\/${host.replaceAll(".", "\\.")}\\$request_uri;`, "s"));
    assert.doesNotMatch(http, /https:\/\/\$host\$request_uri/);
    assert.doesNotMatch(http.slice(0, fallbackAt), /return 301/);
  }
});

test("systemd service isolates the application on its dedicated loopback port", () => {
  const path = "deploy/key-sale-system.service";
  assert.equal(existsSync(resolve(path)), true, `${path} is missing`);
  const source = read(path);

  assert.match(source, /^User=www$/m);
  assert.match(source, /^Group=www$/m);
  assert.match(source, /^EnvironmentFile=\/etc\/key-sale-system\.env$/m);
  assert.match(source, /^Requires=redis-server\.service$/m);
  assert.match(source, /^After=.*redis-server\.service$/m);
  assert.match(source, /^ExecStart=.*uvicorn backend\.main:app --host 127\.0\.0\.1 --port 5230$/m);
  assert.match(source, /^Restart=on-failure$/m);
  assert.match(source, /^UMask=0077$/m);
  assert.match(source, /^NoNewPrivileges=true$/m);
  assert.match(source, /^ReadWritePaths=\/opt\/key-sale-system\/data$/m);
});

test("Certbot hook validates BaoTa Nginx before reloading it", () => {
  const path = "deploy/reload-baota-nginx.sh";
  assert.equal(existsSync(resolve(path)), true, `${path} is missing`);
  const source = read(path);

  assert.match(source, /^#!\/bin\/sh$/m);
  assert.match(source, /\/www\/server\/nginx\/sbin\/nginx/);
  const validateAt = source.indexOf('"$NGINX" -t -c "$CONFIG"');
  const reloadAt = source.indexOf('"$NGINX" -s reload -c "$CONFIG"');
  assert.ok(validateAt >= 0, "hook must validate BaoTa Nginx");
  assert.ok(reloadAt > validateAt, "hook must reload only after validation");
});

test("shell deployment assets keep Linux line endings on Windows", () => {
  const source = read(".gitattributes");
  assert.match(source, /^deploy\/\*\.sh text eol=lf$/m);
});
