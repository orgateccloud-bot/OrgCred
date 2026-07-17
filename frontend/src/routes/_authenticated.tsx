import { createFileRoute, Outlet, redirect } from '@tanstack/react-router'
import { getSession } from '@/auth/supabaseClient'

export const Route = createFileRoute('/_authenticated')({
  beforeLoad: async () => {
    const session = await getSession()
    if (!session) {
      throw redirect({ to: '/login' })
    }
  },
  component: () => <Outlet />,
})
