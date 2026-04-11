# SSL证书配置

## 生产环境SSL证书

生产环境需要使用有效的SSL证书。推荐使用Let's Encrypt免费证书。

## 获取SSL证书

### 方法1: 使用certbot（推荐）

在服务器上执行以下命令：

```bash
# 安装certbot
sudo apt install certbot python3-certbot-nginx

# 获取证书（如果有域名）
sudo certbot --nginx -d your-domain.com

# 如果只有IP地址，可以使用以下方式（需要手动配置）
sudo certbot certonly --standalone -d 39.104.27.129
```

### 方法2: 使用acme.sh（支持IP证书）

```bash
# 安装acme.sh
curl https://get.acme.sh | sh

# 为IP地址申请证书（需要DNS验证或HTTP验证）
acme.sh --issue -d 39.104.27.129 --standalone
```

### 方法3: 自签名证书（仅测试用）

```bash
# 生成自签名证书
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
    -keyout /etc/nginx/ssl/privkey.pem \
    -out /etc/nginx/ssl/fullchain.pem \
    -subj "/C=CN/ST=Beijing/L=Beijing/O=Political News/CN=39.104.27.129"
```

## 证书文件结构

将证书文件放置在以下位置：
- `fullchain.pem` - 完整证书链
- `privkey.pem` - 私钥文件

## Nginx配置

证书配置已在`nginx.conf`中预设：
```nginx
ssl_certificate /etc/nginx/ssl/fullchain.pem;
ssl_certificate_key /etc/nginx/ssl/privkey.pem;
```

## 自动续期

Let's Encrypt证书有效期为90天，建议设置自动续期：

### certbot自动续期
```bash
# 测试续期
sudo certbot renew --dry-run

# 设置自动续期（certbot会自动配置cron任务）
sudo certbot renew --quiet
```

### acme.sh自动续期
acme.sh会自动安装cron任务，无需手动配置。

## 注意事项

1. **安全**: 私钥文件必须严格保密，不要提交到版本控制
2. **续期**: 确保证书自动续期正常工作
3. **备份**: 定期备份证书和私钥
4. **监控**: 监控证书过期时间

## 测试SSL配置

```bash
# 测试SSL配置
nginx -t

# 测试SSL证书
openssl s_client -connect 39.104.27.129:443 -servername 39.104.27.129

# 在线测试
# 访问: https://www.ssllabs.com/ssltest/
```

## 故障排除

### 证书不生效
1. 检查证书文件路径和权限
2. 检查Nginx错误日志：`tail -f /var/log/nginx/error.log`
3. 重启Nginx服务：`nginx -s reload`

### 证书续期失败
1. 检查certbot日志：`journalctl -u certbot`
2. 确保80/443端口可访问
3. 检查防火墙设置