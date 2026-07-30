/**
 * Framer Motion 可复用动画组件
 *
 * FadeIn: 滚动触发淡入动画
 * Magnet: 鼠标跟随磁吸效果
 * AnimatedText: 逐字符滚动驱动文字动画
 */

import {
  motion,
  useScroll,
  useTransform,
} from 'framer-motion';
import {
  useRef,
  useState,
  useEffect,
  type ReactNode,
  type ElementType,
  type CSSProperties,
} from 'react';

// ─── FadeIn ─────────────────────────────────────────────

interface FadeInProps {
  children: ReactNode;
  delay?: number;
  duration?: number;
  x?: number;
  y?: number;
  className?: string;
  style?: CSSProperties;
  as?: ElementType;
}

export function FadeIn({
  children,
  delay = 0,
  duration = 0.7,
  x = 0,
  y = 30,
  className,
  style,
  as = 'div',
}: FadeInProps) {
  const MotionTag = motion.create(as as ElementType);
  return (
    <MotionTag
      initial={{ opacity: 0, x, y }}
      whileInView={{ opacity: 1, x: 0, y: 0 }}
      viewport={{ once: true, margin: '50px', amount: 0 }}
      transition={{ duration, delay, ease: [0.25, 0.1, 0.25, 1] }}
      className={className}
      style={style}
    >
      {children}
    </MotionTag>
  );
}

// ─── Magnet ─────────────────────────────────────────────

interface MagnetProps {
  children: ReactNode;
  padding?: number;
  strength?: number;
  activeTransition?: string;
  inactiveTransition?: string;
  className?: string;
  style?: CSSProperties;
}

export function Magnet({
  children,
  padding = 100,
  strength = 2,
  activeTransition = 'transform 0.3s ease-out',
  inactiveTransition = 'transform 0.6s ease-in-out',
  className,
  style,
}: MagnetProps) {
  const ref = useRef<HTMLDivElement>(null);
  const [offset, setOffset] = useState({ x: 0, y: 0 });
  const [isHovered, setIsHovered] = useState(false);

  useEffect(() => {
    const handleMouseMove = (e: MouseEvent) => {
      if (!ref.current) return;
      const rect = ref.current.getBoundingClientRect();
      const centerX = rect.left + rect.width / 2;
      const centerY = rect.top + rect.height / 2;
      const distX = Math.abs(e.clientX - centerX);
      const distY = Math.abs(e.clientY - centerY);

      if (distX < rect.width / 2 + padding && distY < rect.height / 2 + padding) {
        setIsHovered(true);
        setOffset({
          x: (e.clientX - centerX) / strength,
          y: (e.clientY - centerY) / strength,
        });
      } else {
        setIsHovered(false);
        setOffset({ x: 0, y: 0 });
      }
    };

    window.addEventListener('mousemove', handleMouseMove, { passive: true });
    return () => window.removeEventListener('mousemove', handleMouseMove);
  }, [padding, strength]);

  return (
    <div
      ref={ref}
      className={className}
      style={{
        transform: `translate3d(${offset.x}px, ${offset.y}px, 0)`,
        transition: isHovered ? activeTransition : inactiveTransition,
        willChange: 'transform',
        ...style,
      }}
    >
      {children}
    </div>
  );
}

// ─── AnimatedText ────────────────────────────────────────

interface AnimatedTextProps {
  text: string;
  className?: string;
  style?: CSSProperties;
}

export function AnimatedText({ text, className, style }: AnimatedTextProps) {
  const ref = useRef<HTMLParagraphElement>(null);
  const { scrollYProgress } = useScroll({
    target: ref,
    offset: ['start 0.8', 'end 0.2'],
  });

  const characters = text.split('');

  return (
    <p ref={ref} className={className} style={style}>
      {characters.map((char, i) => {
        const start = i / characters.length;
        const end = start + 1 / characters.length;
        return (
          <CharSpan
            key={i}
            progress={scrollYProgress}
            range={[start, end]}
          >
            {char === ' ' ? '\u00A0' : char}
          </CharSpan>
        );
      })}
    </p>
  );
}

function CharSpan({
  children,
  progress,
  range,
}: {
  children: ReactNode;
  progress: ReturnType<typeof useScroll>['scrollYProgress'];
  range: [number, number];
}) {
  const opacity = useTransform(progress, range, [0.2, 1]);
  return (
    <span style={{ position: 'relative' }}>
      <span style={{ opacity: 0 }}>{children}</span>
      <motion.span
        style={{
          opacity,
          position: 'absolute',
          top: 0,
          left: 0,
          right: 0,
        }}
      >
        {children}
      </motion.span>
    </span>
  );
}
