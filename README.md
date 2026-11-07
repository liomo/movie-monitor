# 上海《沙丘3》IMAX 公开排片线索监控

每 30 分钟由 GitHub Actions 尝试检查五家目标影院的公开排片页面。页面同时出现指定关键词且由未命中变为命中时，使用 Server酱发送微信提醒。

**当前为待配置版本，尚未实际接通影院排片数据。** 五家影院的 `url` 暂为空，脚本会跳过。只有填入经验证、公开可访问的真实排片页面后才会开始检测。关键词命中不等于放票或有余票；JS 动态加载、登录、验证码及反爬限制不受支持。

## 配置
1. 在 `cinemas.json` 中为每家影院填入真实、公开、无需登录的 HTTPS 排片页面地址，并确认响应 HTML 含排片文本。
2. 打开 GitHub 仓库 **Settings → Secrets and variables → Actions → New repository secret**，创建名为 `SERVERCHAN_SENDKEY` 的 Secret，值为 Server酱 SendKey。不要将密钥提交到仓库。
3. 在 **Actions → IMAX screening monitor → Run workflow** 手动测试，查看日志中检查数量和错误。
4. GitHub Actions 按约 30 分钟调度，但运行可能延迟或被暂停。

## 本地测试
```bash
pip install -r requirements.txt
export SERVERCHAN_SENDKEY="your-key"
python monitor.py
```

脚本使用 `state.json` 保存上次检测结果，仅在关键词首次出现或从未命中转为命中时提醒。若 SendKey 未配置，不会将新信号标记为已通知。请注意：如果 SendKey 曾被公开分享，应先在 Server酱平台轮换密钥。
