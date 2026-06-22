---
name: Cyber-Spectrum
colors:
  surface: '#131314'
  surface-dim: '#131314'
  surface-bright: '#3a393a'
  surface-container-lowest: '#0e0e0f'
  surface-container-low: '#1c1b1d'
  surface-container: '#201f21'
  surface-container-high: '#2a2a2b'
  surface-container-highest: '#353436'
  on-surface: '#e5e2e3'
  on-surface-variant: '#bac9cc'
  inverse-surface: '#e5e2e3'
  inverse-on-surface: '#313031'
  outline: '#859396'
  outline-variant: '#3b494c'
  surface-tint: '#13daf1'
  primary: '#cff8ff'
  on-primary: '#00363d'
  primary-container: '#37e8ff'
  on-primary-container: '#006570'
  inverse-primary: '#006874'
  secondary: '#ffaedb'
  on-secondary: '#610048'
  secondary-container: '#aa0080'
  on-secondary-container: '#ffbee1'
  tertiary: '#f7edff'
  on-tertiary: '#42008a'
  tertiary-container: '#e0cbff'
  on-tertiary-container: '#742ed6'
  error: '#ffb4ab'
  on-error: '#690005'
  error-container: '#93000a'
  on-error-container: '#ffdad6'
  primary-fixed: '#98f0ff'
  primary-fixed-dim: '#13daf1'
  on-primary-fixed: '#001f24'
  on-primary-fixed-variant: '#004f58'
  secondary-fixed: '#ffd8ea'
  secondary-fixed-dim: '#ffaedb'
  on-secondary-fixed: '#3c002b'
  on-secondary-fixed-variant: '#880067'
  tertiary-fixed: '#ecdcff'
  tertiary-fixed-dim: '#d5baff'
  on-tertiary-fixed: '#270057'
  on-tertiary-fixed-variant: '#5e00c1'
  background: '#131314'
  on-background: '#e5e2e3'
  surface-variant: '#353436'
  aurora-cyan: '#37E8FF'
  neon-pink: '#FF5CC8'
  royal-purple: '#9B5CFF'
  bright-gold: '#FFE66D'
  surface-glass: rgba(255, 255, 255, 0.03)
  border-glow: rgba(255, 255, 255, 0.15)
typography:
  display-xl:
    fontFamily: Inter
    fontSize: 72px
    fontWeight: '900'
    lineHeight: 80px
    letterSpacing: -0.04em
  display-lg:
    fontFamily: Inter
    fontSize: 48px
    fontWeight: '900'
    lineHeight: 56px
    letterSpacing: -0.03em
  headline-md:
    fontFamily: Inter
    fontSize: 32px
    fontWeight: '200'
    lineHeight: 40px
    letterSpacing: 0.02em
  body-lg:
    fontFamily: Inter
    fontSize: 18px
    fontWeight: '400'
    lineHeight: 28px
  body-md:
    fontFamily: Inter
    fontSize: 16px
    fontWeight: '400'
    lineHeight: 24px
  data-lg:
    fontFamily: JetBrains Mono
    fontSize: 24px
    fontWeight: '600'
    lineHeight: 32px
  data-sm:
    fontFamily: JetBrains Mono
    fontSize: 14px
    fontWeight: '500'
    lineHeight: 20px
  label-caps:
    fontFamily: Inter
    fontSize: 12px
    fontWeight: '700'
    lineHeight: 16px
    letterSpacing: 0.1em
rounded:
  sm: 0.25rem
  DEFAULT: 0.5rem
  md: 0.75rem
  lg: 1rem
  xl: 1.5rem
  full: 9999px
spacing:
  unit: 4px
  gutter: 24px
  margin-safe: 32px
  container-max: 1440px
---

## Brand & Style
The design system is built on a "Cyber-Spectrum" aesthetic, a futuristic fusion of high-performance fintech and vibrant neon-digital art. It targets data-driven investors who seek a high-energy, immersive environment for stock analysis.

The visual style is a sophisticated evolution of **Glassmorphism** and **Retro-Futurism**. It uses a "void" background to ground high-intensity chromatic accents. The emotional goal is to evoke a sense of precision, technical superiority, and high-stakes excitement. Every interface element feels like a light-emitting component within a high-end trading terminal.

## Colors
The palette is centered on a "Deep Void" neutral (#070708) to maximize the luminance of the spectrum colors. 

- **Aurora Cyan** is the primary action color, used for growth, tech indicators, and primary CTAs.
- **Neon Pink** and **Royal Purple** serve as accent colors for AI insights, trend shifts, and secondary data visualizations.
- **Bright Gold** is reserved strictly for premium signals, peak values, and critical alerts.

Contrast is managed by ensuring these high-saturation hues are always paired against the dark neutral or semi-transparent glass surfaces, preventing visual fatigue while maintaining a striking impact.

## Typography
The typographic system relies on a dramatic tension between **Extreme Heavy (900)** and **Extreme Light (200)** weights. 

- **Headlines:** Use Inter with tight letter-spacing for a compact, authoritative feel.
- **Data & Numbers:** JetBrains Mono is used for all financial figures. The use of Tabular Numbers (`tnum`) is mandatory for vertical alignment in tables and tickers.
- **Glow Effect:** Headlines and key data points should have a subtle text-shadow matching their font color (`0px 0px 8px [color]`) at low opacity to simulate light emission.

## Layout & Spacing
This design system utilizes a **Fixed Grid** model for analytical precision.
- **Desktop:** 12-column grid, 24px gutters, 80px margins.
- **Tablet:** 8-column grid, 16px gutters, 40px margins.
- **Mobile:** 4-column grid, 12px gutters, 20px margins.

The spacing rhythm is strictly based on a 4px base unit. Visual groups should be separated by larger clear spaces to emphasize the "floating" nature of the glass modules. Content is structured in modular cards that appear to hover over the infinite dark background.

## Elevation & Depth
Depth is achieved through **Tonal Translucency** rather than traditional drop shadows.
- **Surface Layer:** The base level is the neutral void (#070708).
- **Glass Layer:** Cards and panels use a `backdrop-filter: blur(20px)` with a very subtle white tint (3% opacity).
- **Border Treatment:** Every glass element must have a 1px solid border. Use a linear gradient for the border (top-left to bottom-right) from `rgba(255,255,255,0.2)` to `rgba(255,255,255,0.05)`.
- **Inner Glow:** Apply a subtle `box-shadow: inset 0 1px 1px rgba(255,255,255,0.1)`.

## Shapes
The shape language is "Technical-Soft." A consistent 8px (0.5rem) radius is applied to cards and primary containers to balance the aggressive colors with a modern, approachable geometry. 

Interactive elements like buttons use a slightly higher radius to feel distinct from structural containers. Icons should follow a 2px stroke weight to match the precision of the typography.

## Components
- **Buttons:** Features a `conic-gradient` stroke that appears to "sweep" around the perimeter on hover. The background remains a dark glass to keep text legible.
- **Interactive Cards:** Must implement a "Follow Glow" effect where a radial gradient follows the user's cursor position behind the glass surface.
- **Chips/Badges:** High-contrast, solid fills using the named colors. For example, "Strong Buy" uses Aurora Cyan with black text.
- **Input Fields:** Minimalist design with only a bottom border that glows and expands when focused.
- **Staggered Motion:** Content should use a `cubic-bezier(0.22, 1, 0.36, 1)` transition for the staggered lift effect (y-axis: 20px to 0px).
- **Chromatic Aberration:** Apply a subtle `text-shadow` displacement (1px red shift, -1px blue shift) only during high-speed hover interactions or state transitions.