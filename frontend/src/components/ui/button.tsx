import { forwardRef, type ButtonHTMLAttributes } from 'react'

export type ButtonVariant = 'default' | 'secondary' | 'ghost' | 'danger'
type Props = ButtonHTMLAttributes<HTMLButtonElement> & { variant?: ButtonVariant; size?: 'normal' | 'icon' | 'small' }

export const Button = forwardRef<HTMLButtonElement, Props>(function Button(
  { className = '', variant = 'default', size = 'normal', type = 'button', ...props }, ref
) {
  return <button {...props} type={type} ref={ref} data-slot="button" className={`btn ${variant} ${size} ${className}`} />
})
