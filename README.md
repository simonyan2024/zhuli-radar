# 主力雷达 v0.3

上证主板研究雷达：大盘闸门 + 量价阶段 + 相对强弱 + 可选 easy-tdx 增强。

## 与 easy-tdx 的结合

| 能力 | 来源 |
|------|------|
| 量价阶段 / 四级建议 / 大盘静默 | 主力雷达自研（主逻辑） |
| K线 / 报价 | **优先 easy-tdx（通达信）**，失败回退公开 HTTP |
| MACD / RSI / KDJ / 布林 | easy-tdx 指标引擎；无包时用内置简化算法 |
| 资金流 | easy-tdx 可用时附加（不覆盖定级） |
| 回测 / 雷达 UI / 自选 | 主力雷达 |

```bash
pip install -r requirements.txt
# 可选：pip install easy-tdx
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

调用顺序：通达信(easy-tdx) → AkShare → Tushare → 公开 HTTP。
