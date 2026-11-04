import type { Metadata } from 'next'
import { dmca } from '@/content/dmca'
import { PolicyPage } from '@/components/PolicyPage'

export const metadata: Metadata = {
  title: 'DMCA Policy | LLM Wiki',
  description: 'DMCA designated agent and copyright notice policy for LLM Wiki.',
}

export default function DmcaPage() {
  return <PolicyPage content={dmca} />
}
