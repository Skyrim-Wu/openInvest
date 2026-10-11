import { useEffect } from 'react'
import './page.css'
import body from './body.html?raw'
import { init } from './logic.js'

// 页面与逻辑由 sync.py 从 ../scripts/index.html 生成，这里只负责挂载；
// 接口仍在 fund.longsizhuo.com（限额、书记员闸都在服务端）
const API = import.meta.env.VITE_API_URL || 'https://fund.longsizhuo.com'

export default function App() {
  useEffect(() => init(API), [])
  return <div dangerouslySetInnerHTML={{ __html: body }} />
}
