/** @type {import('next').NextConfig} */
const backendOrigin = (process.env.BACKEND_ORIGIN || 'http://127.0.0.1:8000').replace(/\/$/, '')

const nextConfig = {
  async rewrites() {
    return [
      {
        source: '/api/v1/:path*',
        destination: `${backendOrigin}/api/v1/:path*`
      }
    ]
  }
}
module.exports = nextConfig
