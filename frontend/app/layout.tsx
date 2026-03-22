import type { Metadata } from 'next'
import './globals.css'
import Sidebar from '@/components/Sidebar'

export const metadata: Metadata = {
  title: 'PredictAI Dashboard',
  description: 'Prediction Market AI Trading Dashboard'
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark">
      <body className="bg-gray-900">
        <div className="flex min-h-screen">
          {/* Sidebar */}
          <Sidebar />

          {/* Main content - offset by sidebar width */}
          <main className="flex-1 pl-16 md:pl-60">
            <div className="min-h-screen p-6 md:p-8">{children}</div>
          </main>
        </div>
      </body>
    </html>
  )
}
