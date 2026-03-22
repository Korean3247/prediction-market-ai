import { type LucideIcon, Inbox } from 'lucide-react'

interface EmptyStateProps {
  message: string
  icon?: LucideIcon
}

export default function EmptyState({ message, icon: Icon = Inbox }: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center justify-center py-16 text-center">
      <div className="mb-4 flex h-16 w-16 items-center justify-center rounded-full bg-gray-800">
        <Icon className="h-8 w-8 text-gray-600" />
      </div>
      <p className="text-sm text-gray-500">{message}</p>
    </div>
  )
}
