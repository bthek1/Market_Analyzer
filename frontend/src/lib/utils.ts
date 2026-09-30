import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

/** Format a Date as "dd/mm/yyyy, hh:mm:ss AM/PM" (e.g. 28/06/2026, 11:30:00 AM). */
export function formatDateTime(date: Date): string {
  const dd = String(date.getDate()).padStart(2, "0")
  const mm = String(date.getMonth() + 1).padStart(2, "0")
  const yyyy = date.getFullYear()
  let hours = date.getHours()
  const period = hours >= 12 ? "PM" : "AM"
  hours = hours % 12 || 12
  const hh = String(hours).padStart(2, "0")
  const min = String(date.getMinutes()).padStart(2, "0")
  const ss = String(date.getSeconds()).padStart(2, "0")
  return `${dd}/${mm}/${yyyy}, ${hh}:${min}:${ss} ${period}`
}
