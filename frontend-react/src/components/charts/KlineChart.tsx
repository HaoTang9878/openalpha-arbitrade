/**
 * K 线图表组件
 *
 * 使用 TradingView Lightweight Charts 渲染专业 K 线图。
 * 支持蜡烛图 + 成交量柱状图，涨绿跌红样式。
 * 对标 Binance/OKX 的 K 线可视化。
 *
 * 使用方法：
 *   <KlineChart klines={klines} symbol="BTC/USDT" />
 */

import { useEffect, useRef } from 'react';
import {
  createChart,
  ColorType,
  CrosshairMode,
  type IChartApi,
  type ISeriesApi,
  type CandlestickData,
  type HistogramData,
  type UTCTimestamp,
} from 'lightweight-charts';

interface KlineData {
  timestamp: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

interface KlineChartProps {
  /** K 线数据数组 */
  klines: KlineData[];
  /** 交易对名称 */
  symbol?: string;
  /** 高度（px），默认 400 */
  height?: number;
}

export function KlineChart({ klines, symbol = '', height = 400 }: KlineChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleRef = useRef<ISeriesApi<'Candlestick'> | null>(null);
  const volumeRef = useRef<ISeriesApi<'Histogram'> | null>(null);

  /** 初始化图表 */
  useEffect(() => {
    if (!containerRef.current) return;

    const chart = createChart(containerRef.current, {
      width: containerRef.current.clientWidth,
      height,
      layout: {
        background: { type: ColorType.Solid, color: 'transparent' },
        textColor: 'var(--color-text-secondary)',
        fontFamily: "'IBM Plex Mono', monospace",
        fontSize: 11,
      },
      grid: {
        vertLines: { color: 'rgba(122,140,155,0.08)' },
        horzLines: { color: 'rgba(122,140,155,0.08)' },
      },
      crosshair: {
        mode: CrosshairMode.Normal,
        vertLine: {
          color: 'rgba(214,175,110,0.5)',
          width: 1,
          style: 2,
          labelBackgroundColor: 'var(--color-accent)',
        },
        horzLine: {
          color: 'rgba(214,175,110,0.5)',
          width: 1,
          style: 2,
          labelBackgroundColor: 'var(--color-accent)',
        },
      },
      rightPriceScale: {
        borderColor: 'var(--color-border)',
      },
      timeScale: {
        borderColor: 'var(--color-border)',
        timeVisible: true,
        secondsVisible: false,
      },
    });

    // 蜡烛图系列
    const candleSeries = chart.addCandlestickSeries({
      upColor: 'var(--color-up)',
      downColor: 'var(--color-down)',
      borderUpColor: 'var(--color-up)',
      borderDownColor: 'var(--color-down)',
      wickUpColor: 'var(--color-up)',
      wickDownColor: 'var(--color-down)',
    });

    // 成交量系列
    const volumeSeries = chart.addHistogramSeries({
      priceFormat: { type: 'volume' },
      priceScaleId: 'volume',
    });
    chart.priceScale('volume').applyOptions({
      scaleMargins: { top: 0.8, bottom: 0 },
    });

    chartRef.current = chart;
    candleRef.current = candleSeries;
    volumeRef.current = volumeSeries;

    // 响应式调整
    const handleResize = () => {
      if (containerRef.current && chartRef.current) {
        chartRef.current.applyOptions({
          width: containerRef.current.clientWidth,
        });
      }
    };
    window.addEventListener('resize', handleResize);

    return () => {
      window.removeEventListener('resize', handleResize);
      chart.remove();
      chartRef.current = null;
    };
  }, [height]);

  /** 更新数据 */
  useEffect(() => {
    if (!candleRef.current || !volumeRef.current || klines.length === 0) return;

    // 转换为 Lightweight Charts 数据格式
    const candleData: CandlestickData[] = klines.map((k) => ({
      time: Math.floor(k.timestamp / 1000) as UTCTimestamp,
      open: k.open,
      high: k.high,
      low: k.low,
      close: k.close,
    }));

    const volumeData: HistogramData[] = klines.map((k) => ({
      time: Math.floor(k.timestamp / 1000) as UTCTimestamp,
      value: k.volume,
      color: k.close >= k.open
        ? 'rgba(14,203,129,0.5)'
        : 'rgba(246,70,93,0.5)',
    }));

    candleRef.current.setData(candleData);
    volumeRef.current.setData(volumeData);
    chartRef.current?.timeScale().fitContent();
  }, [klines]);

  if (klines.length === 0) {
    return (
      <div
        className="flex items-center justify-center rounded-lg border"
        style={{ height, borderColor: 'var(--color-border)', color: 'var(--color-text-muted)' }}
      >
        <span className="text-sm">暂无 K 线数据</span>
      </div>
    );
  }

  return (
    <div className="panel">
      {symbol && (
        <div className="panel-header">
          <span className="panel-title">{symbol} K 线图</span>
        </div>
      )}
      <div ref={containerRef} style={{ height }} />
    </div>
  );
}
