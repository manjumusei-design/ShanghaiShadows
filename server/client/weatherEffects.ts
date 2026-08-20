const FOG_KEYFRAMES = `
@keyframes weatherFogWaft {
  0%   { transform: translate(0, 0) scale(1); opacity: 0.2; }
  25%  { transform: translate(10px, -5px) scale(1.1); opacity: 0.3; }
  50%  { transform: translate(5px, 5px) scale(0.95); opacity: 0.15; }
  75%  { transform: translate(-5px, -10px) scale(1.05); opacity: 0.25; }
  100% { transform: translate(0, 0) scale(1); opacity: 0.2; }
}`

export class WeatherEffects {
  private overlay: HTMLElement | null = null
  private canvas: HTMLCanvasElement | null = null
  private ctx: CanvasRenderingContext2D | null = null
  private animFrame: number = 0
  private currentType: string = 'clear'
  private raindrops: Array<{ x: number; y: number; speed: number; length: number; opacity: number }> = []
  private snowflakes: Array<{ x: number; y: number; speed: number; drift: number; size: number; opacity: number }> = []
  private styleEl: HTMLStyleElement | null = null

  mount(parentEl: HTMLElement): void {
    if (this.overlay) return

    const overlay = document.createElement('div')
    overlay.id = 'weather-overlay'
    overlay.style.cssText = 'position:fixed;inset:0;pointer-events:none;z-index:9999;overflow:hidden;'
    parentEl.appendChild(overlay)
    this.overlay = overlay

    const canvas = document.createElement('canvas')
    canvas.style.cssText = 'position:absolute;inset:0;width:100%;height:100%;'
    overlay.appendChild(canvas)
    this.canvas = canvas
    this.ctx = canvas.getContext('2d')!

    const style = document.createElement('style')
    style.textContent = FOG_KEYFRAMES
    document.head.appendChild(style)
    this.styleEl = style

    this._resize()
    window.addEventListener('resize', this._resize)
  }

  private _resize = () => {
    if (!this.canvas) return
    this.canvas.width = window.innerWidth
    this.canvas.height = window.innerHeight
  }

  setWeather(type: string): void {
    this.currentType = type
    this._clearCanvas()

    if (!this.overlay) return

    const toRemove: Node[] = []
    for (let i = this.overlay.children.length - 1; i >= 0; i--) {
      const child = this.overlay.children[i]
      if (child !== this.canvas) toRemove.push(child)
    }
    toRemove.forEach(node => node.parentNode?.removeChild(node))

    switch (type) {
      case 'rain':
        this._startRain()
        break
      case 'fog':
        this._startFog()
        break
      case 'snow':
        this._startSnow()
        break
      case 'storm':
        this._startStorm()
        break
      default:
        this._stopAnimation()
        break
    }
  }

  destroy(): void {
    this._stopAnimation()
    window.removeEventListener('resize', this._resize)
    if (this.styleEl) {
      this.styleEl.remove()
      this.styleEl = null
    }
    if (this.overlay) {
      this.overlay.remove()
      this.overlay = null
    }
    this.canvas = null
    this.ctx = null
  }

  private _clearCanvas(): void {
    this._stopAnimation()
    if (this.canvas) {
      this.ctx?.clearRect(0, 0, this.canvas.width, this.canvas.height)
    }
  }

  private _stopAnimation(): void {
    if (this.animFrame) {
      cancelAnimationFrame(this.animFrame)
      this.animFrame = 0
    }
  }

  private _resizeCanvas(): void {
    if (!this.canvas) return
    const w = window.innerWidth
    const h = window.innerHeight
    if (this.canvas.width !== w || this.canvas.height !== h) {
      this.canvas.width = w
      this.canvas.height = h
    }
  }

  private _startRain(): void {
    this._resizeCanvas()
    const w = this.canvas!.width
    const count = 80 + Math.floor(Math.random() * 40)
    this.raindrops = Array.from({ length: count }, () => ({
      x: Math.random() * w,
      y: Math.random() * -600,
      speed: 8 + Math.random() * 10,
      length: 12 + Math.random() * 10,
      opacity: 0.1 + Math.random() * 0.15
    }))
    this._animateRain()
  }

  private _animateRain = (): void => {
    const canvas = this.canvas
    const ctx = this.ctx
    if (!canvas || !ctx) return

    this._resizeCanvas()
    ctx.clearRect(0, 0, canvas.width, canvas.height)

    for (const d of this.raindrops) {
      d.y += d.speed
      d.x += 2 // wind angle
      if (d.y > canvas.height) {
        d.y = -20
        d.x = Math.random() * canvas.width
      }
      ctx.strokeStyle = `rgba(180,200,220,${d.opacity})`
      ctx.lineWidth = 1
      ctx.beginPath()
      ctx.moveTo(d.x, d.y)
      ctx.lineTo(d.x + 6, d.y + d.length)
      ctx.stroke()
    }

    this.animFrame = requestAnimationFrame(this._animateRain)
  }

  private _startFog(): void {
    if (!this.overlay) return
    const fog = document.createElement('div')
    fog.style.cssText = `
      position:absolute;inset:0;
      background: radial-gradient(ellipse at 50% 50%, rgba(180,180,190,0.08) 0%, transparent 70%);
      animation: weatherFogWaft 10s ease-in-out infinite;
    `
    this.overlay.insertBefore(fog, this.canvas)
  }

  private _startSnow(): void {
    this._resizeCanvas()
    const w = this.canvas!.width
    const count = 40 + Math.floor(Math.random() * 20)
    this.snowflakes = Array.from({ length: count }, () => ({
      x: Math.random() * w,
      y: Math.random() * -500,
      speed: 1.0 + Math.random() * 2.0,
      drift: 0.3 + Math.random() * 0.8,
      size: 2 + Math.random() * 4,
      opacity: 0.3 + Math.random() * 0.4
    }))
    this._animateSnow()
  }

  private _animateSnow = (): void => {
    const canvas = this.canvas
    const ctx = this.ctx
    if (!canvas || !ctx) return

    this._resizeCanvas()
    ctx.clearRect(0, 0, canvas.width, canvas.height)

    for (const s of this.snowflakes) {
      s.y += s.speed
      s.x += Math.sin(s.y * 0.02) * s.drift
      if (s.y > canvas.height) {
        s.y = -10
        s.x = Math.random() * canvas.width
      }
      ctx.fillStyle = `rgba(255,255,255,${s.opacity})`
      ctx.beginPath()
      ctx.arc(s.x, s.y, s.size, 0, Math.PI * 2)
      ctx.fill()
    }

    this.animFrame = requestAnimationFrame(this._animateSnow)
  }

  private _startStorm(): void {
    this._resizeCanvas()
    const w = this.canvas!.width
    const count = 80 + Math.floor(Math.random() * 40)
    this.raindrops = Array.from({ length: count }, () => ({
      x: Math.random() * w,
      y: Math.random() * -600,
      speed: 12 + Math.random() * 14,
      length: 15 + Math.random() * 12,
      opacity: 0.15 + Math.random() * 0.2
    }))

    if (this.overlay) {
      const flash = document.createElement('div')
      flash.id = 'storm-flash'
      flash.style.cssText = 'position:absolute;inset:0;background:rgba(255,255,255,0);transition:background 0.05s;'
      this.overlay.insertBefore(flash, this.canvas)
    }

    this._animateStorm()
    this._scheduleLightning()
  }

  private _animateStorm = (): void => {
    const canvas = this.canvas
    const ctx = this.ctx
    if (!canvas || !ctx) return

    this._resizeCanvas()
    ctx.clearRect(0, 0, canvas.width, canvas.height)

    for (const d of this.raindrops) {
      d.y += d.speed
      d.x += 3
      if (d.y > canvas.height) {
        d.y = -20
        d.x = Math.random() * canvas.width
      }
      ctx.strokeStyle = `rgba(180,200,220,${d.opacity})`
      ctx.lineWidth = 1.5
      ctx.beginPath()
      ctx.moveTo(d.x, d.y)
      ctx.lineTo(d.x + 8, d.y + d.length)
      ctx.stroke()
    }

    this.animFrame = requestAnimationFrame(this._animateStorm)
  }

  private _scheduleLightning(): void {
    if (this.currentType !== 'storm') return
    const delay = 3000 + Math.random() * 5000
    setTimeout(() => {
      if (this.currentType !== 'storm') return
      this._flashLightning()
      this._scheduleLightning()
    }, delay)
  }

  private _flashLightning(): void {
    const flash = this.overlay?.querySelector('#storm-flash') as HTMLElement
    if (!flash) return
    flash.style.background = 'rgba(255,255,255,0.04)'
    setTimeout(() => { flash.style.background = 'rgba(255,255,255,0)' }, 80)
  }
}
