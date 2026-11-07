import type { Metadata } from 'next'

export const metadata: Metadata = {
  title: 'AI-Powered Workflow Automator',
  description: 'Zapier-like pipeline automation with LLM support',
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  )
}
