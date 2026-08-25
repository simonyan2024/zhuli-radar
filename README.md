# 主力雷达 v0.3

上证主板研究雷达：大盘闸门 + 量价阶段 + 相对强弱。

## 与 easy-tdx 的结合

| 能力 | 来源 |
|------|------|
| 量价阶段 / 四级建议 / 大盘静默 | 主力雷达自研（主逻辑） |
| K线 / 报价 
| MACD / RSI / KDJ / 布林 | 
| 资金流 | 
| 回测 / 雷达 UI / 自选 | 主力雷达 |

```bash
pip install -r requirements.txt
python -m uvicorn server.main:app --host 0.0.0.0 --port 8765
```

研究辅助，不构成投资建议。


## 数据源：AkShare / Tushare

安装：

```bash
pip install akshare tushare pandas
```

Tushare 需在 [tushare.pro](https://tushare.pro) 注册拿到 token，部署时设置环境变量：

```bash
export TUSHARE_TOKEN=你的token
```

Render：Dashboard → Environment → 添加 `TUSHARE_TOKEN`。

调用顺序：AkShare → Tushare → 公开 HTTP。
