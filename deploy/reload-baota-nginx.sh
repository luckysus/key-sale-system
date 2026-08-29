#!/bin/sh
set -eu

NGINX=/www/server/nginx/sbin/nginx
CONFIG=/www/server/nginx/conf/nginx.conf

"$NGINX" -t -c "$CONFIG"
"$NGINX" -s reload -c "$CONFIG"
