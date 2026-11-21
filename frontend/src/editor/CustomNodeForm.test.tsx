import { fireEvent, render, screen } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import '../i18n'
import { CustomNodeForm } from './CustomNodeForm'

it('submits a named mapping of nested input fields', () => {
  const save = vi.fn()
  render(<CustomNodeForm onSave={save} onCancel={() => {}} saving={false} />)
  fireEvent.change(screen.getByLabelText('Название'), { target: { value: 'Риски' } })
  fireEvent.change(screen.getByLabelText('Поле результата'), { target: { value: 'high' } })
  fireEvent.change(screen.getByLabelText('Путь или условие'), { target: { value: 'counts.HIGH' } })
  fireEvent.click(screen.getByRole('button', { name: 'Сохранить ноду' }))
  expect(save).toHaveBeenCalledWith({ name: 'Риски', fields: { high: 'counts.HIGH' } })
})
