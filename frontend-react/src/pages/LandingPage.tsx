/**
 * OpenAlpha 套利系统 Landing 页面
 *
 * 基于 3D Creator portfolio 设计风格，包含：
 * - Hero: 渐变标题 + 磁吸效果
 * - Features: 滚动驱动 marquee
 * - About: 逐字符滚动文字动画
 * - Stats: 关键数据展示
 * - CTA: 渐变按钮
 */

import { useRef } from 'react';
import { useScroll, useTransform, motion } from 'framer-motion';
import {
  TrendingUp,
  ShieldCheck,
  Zap,
  Activity,
  ArrowRight,
} from 'lucide-react';
import { FadeIn, AnimatedText } from '../components/animation/Motion';
import { ContactButton, LiveProjectButton } from '../components/common/GradientButton';

// ─── Hero Section ────────────────────────────────────────

function HeroSection() {
  return (
    <section
      className="relative min-h-screen flex flex-col"
      style={{ overflowX: 'clip', background: '#070B10' }}
    >
      {/* 导航栏 */}
      <FadeIn delay={0} y={-20}>
        <nav className="flex justify-between items-center px-6 md:px-10 pt-6 md:pt-8">
          <span className="text-sm md:text-lg lg:text-xl font-bold" style={{ color: '#D4A458' }}>
            OpenAlpha
          </span>
          <div className="flex gap-4 sm:gap-6 md:gap-10">
            {['功能', '策略', '数据', '文档'].map((item) => (
              <a
                key={item}
                href={`#${item}`}
                className="text-xs sm:text-sm md:text-lg lg:text-xl font-medium uppercase tracking-wider transition-opacity hover:opacity-70"
                style={{ color: '#D7E2EA' }}
              >
                {item}
              </a>
            ))}
          </div>
        </nav>
      </FadeIn>

      {/* 主标题 */}
      <div className="overflow-hidden mt-8 sm:mt-12 md:mt-16 px-4 text-center">
        <FadeIn delay={0.15} y={40}>
          <h1
            className="hero-heading font-black uppercase tracking-tight leading-none w-full"
            style={{ fontSize: 'clamp(3rem, 14vw, 17vw)' }}
          >
            套利引擎
          </h1>
        </FadeIn>
      </div>

      {/* 底部栏 */}
      <div className="flex-1" />
      <div className="flex flex-col sm:flex-row justify-between items-center gap-6 px-6 md:px-10 pb-8 sm:pb-10 md:pb-12">
        <FadeIn delay={0.35} y={20}>
          <p
            className="font-light uppercase tracking-wide leading-snug text-center sm:text-left"
            style={{
              color: '#D7E2EA',
              fontSize: 'clamp(0.75rem, 1.4vw, 1.5rem)',
              maxWidth: 'clamp(160px, 26vw, 300px)',
            }}
          >
            跨交易所实时监控，自动捕捉价差，毫秒级执行
          </p>
        </FadeIn>

        <FadeIn delay={0.5} y={20}>
          <ContactButton label="开始使用" />
        </FadeIn>
      </div>
    </section>
  );
}

// ─── Marquee Section ─────────────────────────────────────

function MarqueeSection() {
  const sectionRef = useRef<HTMLElement>(null);
  const { scrollYProgress } = useScroll({
    target: sectionRef,
    offset: ['start end', 'end start'],
  });

  const x1 = useTransform(scrollYProgress, [0, 1], ['-200px', '200px']);
  const x2 = useTransform(scrollYProgress, [0, 1], ['200px', '-200px']);

  const features = [
    { icon: TrendingUp, label: '价差检测', color: '#0ECB81' },
    { icon: Zap, label: '毫秒执行', color: '#FBBF24' },
    { icon: ShieldCheck, label: '风控熔断', color: '#F6465D' },
    { icon: Activity, label: 'L2深度', color: '#2196F3' },
  ];

  const row1 = [...features, ...features, ...features];
  const row2 = [...features.slice().reverse(), ...features.slice().reverse(), ...features.slice().reverse()];

  return (
    <section
      ref={sectionRef}
      className="relative py-24 sm:py-32 md:py-40 pb-10"
      style={{ background: '#070B10' }}
    >
      <motion.div style={{ x: x1 }} className="flex gap-3 mb-3 will-change-transform">
        {row1.map((item, i) => (
          <FeatureTile key={i} {...item} />
        ))}
      </motion.div>
      <motion.div style={{ x: x2 }} className="flex gap-3 will-change-transform">
        {row2.map((item, i) => (
          <FeatureTile key={i} {...item} />
        ))}
      </motion.div>
    </section>
  );
}

function FeatureTile({ icon: Icon, label, color }: { icon: typeof TrendingUp; label: string; color: string }) {
  return (
    <div
      className="flex-shrink-0 flex items-center gap-3 px-8 py-6 rounded-2xl"
      style={{
        width: '320px',
        background: 'color-mix(in srgb, var(--color-bg-card) 60%, transparent)',
        border: '1px solid var(--color-border)',
        backdropFilter: 'blur(8px)',
      }}
    >
      <Icon className="w-8 h-8 flex-shrink-0" style={{ color }} strokeWidth={1.5} />
      <span className="text-lg font-semibold" style={{ color: '#D7E2EA' }}>
        {label}
      </span>
    </div>
  );
}

// ─── About Section ───────────────────────────────────────

function AboutSection() {
  return (
    <section
      className="relative min-h-screen flex flex-col items-center justify-center px-5 sm:px-8 md:px-10 py-20"
      id="功能"
    >
      <FadeIn delay={0} y={40}>
        <h2
          className="hero-heading font-black uppercase leading-none tracking-tight text-center"
          style={{ fontSize: 'clamp(3rem, 12vw, 160px)' }}
        >
          核心优势
        </h2>
      </FadeIn>

      <div className="flex flex-col items-center gap-14 md:gap-20 mt-10">
        <AnimatedText
          text="通过 WebSocket 实时订阅多交易所价格与 L2 订单簿数据，基于深度计算实际滑点，扣除手续费后自动过滤盈利机会，毫秒级响应执行套利交易。"
          className="font-medium text-center leading-relaxed"
          style={{
            color: '#D7E2EA',
            maxWidth: '560px',
            fontSize: 'clamp(1rem, 2vw, 1.35rem)',
          }}
        />

        <FadeIn delay={0.2} y={20}>
          <ContactButton label="立即体验" />
        </FadeIn>
      </div>
    </section>
  );
}

// ─── Stats Section ───────────────────────────────────────

const STATS = [
  { number: '8', label: '主流交易所', desc: 'Binance/OKX/Bybit/Gate 等' },
  { number: '40+', label: '交易对监控', desc: '覆盖 9 大赛道' },
  { number: '3s', label: '扫描间隔', desc: 'WebSocket 实时推送' },
  { number: '4', label: '重风控限制', desc: '持仓/亏损/次数/敞口' },
];

function StatsSection() {
  return (
    <section
      className="rounded-t-[40px] md:rounded-t-[60px] py-20 sm:py-24 md:py-32 px-5 sm:px-8 md:px-10"
      style={{ background: '#FFFFFF' }}
    >
      <FadeIn delay={0} y={40}>
        <h2
          className="font-black uppercase text-center mb-16 sm:mb-20 md:mb-28"
          style={{ color: '#0C0C0C', fontSize: 'clamp(3rem, 12vw, 160px)' }}
        >
          数据规模
        </h2>
      </FadeIn>

      <div className="max-w-5xl mx-auto">
        {STATS.map((stat, i) => (
          <FadeIn key={i} delay={i * 0.1} y={30}>
            <div
              className="flex items-center gap-8 py-8 sm:py-10 md:py-12"
              style={{
                borderBottom:
                  i < STATS.length - 1
                    ? '1px solid rgba(12, 12, 12, 0.15)'
                    : 'none',
              }}
            >
              <span
                className="font-black flex-shrink-0"
                style={{
                  color: '#0C0C0C',
                  fontSize: 'clamp(3rem, 10vw, 140px)',
                  lineHeight: 1,
                }}
              >
                {stat.number}
              </span>
              <div className="flex flex-col">
                <span
                  className="font-medium uppercase"
                  style={{ color: '#0C0C0C', fontSize: 'clamp(1rem, 2.2vw, 2.1rem)' }}
                >
                  {stat.label}
                </span>
                <span
                  className="font-light leading-relaxed mt-1"
                  style={{
                    color: 'rgba(12, 12, 12, 0.6)',
                    fontSize: 'clamp(0.85rem, 1.6vw, 1.25rem)',
                    maxWidth: '500px',
                  }}
                >
                  {stat.desc}
                </span>
              </div>
            </div>
          </FadeIn>
        ))}
      </div>
    </section>
  );
}

// ─── CTA Section ──────────────────────────────────────────

function CTASection() {
  return (
    <section
      className="rounded-t-[40px] md:rounded-t-[60px] -mt-10 md:-mt-14 relative z-10 py-20 px-5 sm:px-8 md:px-10"
      style={{ background: '#070B10' }}
      id="策略"
    >
      <div className="max-w-4xl mx-auto text-center">
        <FadeIn delay={0} y={40}>
          <h2
            className="hero-heading font-black uppercase leading-none tracking-tight"
            style={{ fontSize: 'clamp(2.5rem, 10vw, 120px)' }}
          >
            开始套利
          </h2>
        </FadeIn>

        <FadeIn delay={0.2} y={30}>
          <p
            className="mt-6 mb-10 font-light leading-relaxed"
            style={{
              color: '#D7E2EA',
              fontSize: 'clamp(1rem, 2vw, 1.5rem)',
              maxWidth: '600px',
              margin: '1.5rem auto 2.5rem',
            }}
          >
            部署 Docker 一键启动，支持模拟交易和实盘模式，
            通过 Telegram 实时接收套利机会和交易通知。
          </p>
        </FadeIn>

        <FadeIn delay={0.4} y={20}>
          <div className="flex flex-wrap gap-4 justify-center">
            <ContactButton label="立即部署" />
            <LiveProjectButton label="查看文档" />
          </div>
        </FadeIn>

        <FadeIn delay={0.6} y={20}>
          <div
            className="mt-16 flex items-center justify-center gap-2 text-sm"
            style={{ color: 'rgba(215, 226, 234, 0.4)' }}
          >
            <span>OpenAlpha Arbitrage v2.0</span>
            <ArrowRight className="w-3 h-3" strokeWidth={1.5} />
            <span>React + TypeScript + FastAPI + CCXT</span>
          </div>
        </FadeIn>
      </div>
    </section>
  );
}

// ─── Main Export ─────────────────────────────────────────

export function LandingPage() {
  return (
    <div
      className="min-h-screen w-full"
      style={{ background: '#070B10', overflowX: 'clip', color: '#D7E2EA' }}
    >
      <HeroSection />
      <MarqueeSection />
      <AboutSection />
      <StatsSection />
      <CTASection />
    </div>
  );
}
