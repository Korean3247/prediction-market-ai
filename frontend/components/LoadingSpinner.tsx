export default function LoadingSpinner({ size = 'md' }: { size?: 'sm' | 'md' | 'lg' }) {
  const sizeMap = {
    sm: 'h-5 w-5',
    md: 'h-8 w-8',
    lg: 'h-12 w-12'
  }

  return (
    <div className="flex items-center justify-center py-12">
      <div
        className={`animate-spin rounded-full border-2 border-gray-700 border-t-sky-500 ${sizeMap[size]}`}
      />
    </div>
  )
}
