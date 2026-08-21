export interface WebSocketConfig {
  uri: string
  onOpen?: () => void
  onClose?: (data: any) => void
  onMessage?: (data: any) => void
  onError?: (event: Event) => void
  reconnectAttempts?: number
  reconnectDelay?: number
}

export class WebsocketService {
  private ws: WebSocket | null = null
  private config: WebSocketConfig
  private reconnectCount: number = 0
  private reconnectTimer: number | null = null
  private intentionallyClosed: boolean = false

  constructor(config: WebSocketConfig) {
    this.config = {
      reconnectAttempts: 5,
      reconnectDelay: 3000,
      ...config
    }
  }

  connect(): Promise<void> {
    return new Promise((resolve, reject) => {
      this.intentionallyClosed = false

      try {
        this.ws = new WebSocket(this.config.uri)
      } catch (e) {
        reject(e)
        return
      }

      this.ws.onopen = () => {
        this.reconnectCount = 0
        this.config.onOpen?.()
        resolve()
      }

      this.ws.onclose = (event) => {
        this.config.onClose?.(event)
        if (!this.intentionallyClosed) {
          this.attemptReconnect()
        }
      }

      this.ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data)
          this.config.onMessage?.(data)
        } catch (e) {
          console.error('Failed to parse message:', event.data)
        }
      }

      this.ws.onerror = (event) => {
        this.config.onError?.(event)
        reject(event)
      }
    })
  }

  send(message: string): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(message)
    } else {
      console.warn('WebSocket not connected, cannot send:', message)
    }
  }

  disconnect(): void {
    this.intentionallyClosed = true
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer)
      this.reconnectTimer = null
    }
    if (this.ws) {
      this.ws.close()
      this.ws = null
    }
  }

  isConnected(): boolean {
    return this.ws?.readyState === WebSocket.OPEN
  }

  getReadyState(): number {
    return this.ws?.readyState ?? WebSocket.CLOSED
  }

  private attemptReconnect(): void {
    if (this.intentionallyClosed) return

    if (this.reconnectCount >= (this.config.reconnectAttempts || 5)) {
      console.error('Max reconnect attempts reached')
      return
    }

    this.reconnectCount++
    console.log(`Reconnecting... Attempt ${this.reconnectCount}/${this.config.reconnectAttempts}`)

    this.reconnectTimer = window.setTimeout(() => {
      this.connect().catch((e) => {
        console.error('Reconnection failed:', e)
      })
    }, this.config.reconnectDelay)
  }
}
let wsInstance: WebSocketService | null = null
  
export function getWebSocket(): WebSocketService | null {
  return wsInstance
}

export function createWebSocket(config: WebSocketConfig): WebSocketService {
  wsInstance = new WebSocketService(config)
  return wsInstance
}

