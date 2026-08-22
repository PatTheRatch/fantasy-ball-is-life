import { Outlet } from "react-router-dom";

// App shell: header + content outlet. The league nav lands in a later bite.
export function Layout() {
  return (
    <div className="min-h-screen bg-gray-50 text-gray-900">
      <header className="border-b border-gray-200 bg-white px-6 py-4">
        <h1 className="text-lg font-semibold">Full Court Press</h1>
      </header>
      <main className="mx-auto max-w-3xl px-6 py-8">
        <Outlet />
      </main>
    </div>
  );
}
