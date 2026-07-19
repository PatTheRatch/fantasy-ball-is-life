import { Outlet } from 'react-router-dom'
import { BottomTabBar } from '../components/BottomTabBar'
import { TopNav } from '../components/TopNav'

export function AppLayout() {
  return (
    <div className="flex min-h-dvh flex-col">
      <TopNav />
      <div className="border-b border-pg-border bg-pg-bg/90 px-4 py-3 backdrop-blur-md md:hidden">
        <p className="text-base font-bold tracking-tight text-white">
          Full Court Press
        </p>
      </div>
      <main className="mx-auto w-full max-w-6xl flex-1 px-4 pb-24 pt-4 md:px-6 md:pb-8 md:pt-6">
        <Outlet />
      </main>
      <BottomTabBar />
    </div>
  )
}
