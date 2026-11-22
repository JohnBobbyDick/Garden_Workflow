import { describe, expect, it } from 'vitest'
import { legacyRedirect, panelFromSearch, withPanel } from './routes'

describe('legacyRedirect: old addresses open their equivalent in the workspace', () => {
  it.each([
    ['/workflows/abc', '', '/c/abc'],
    ['/workflows', '', '/'],
    ['/pr', '?run=r1&finding=f2', '/runs/r1?finding=f2'],
    ['/pr', '', '/'],
    ['/templates', '', '/?panel=templates'],
    ['/integration', '', '/?panel=ci'],
    ['/settings', '?tab=credentials', '/?panel=settings&tab=credentials'],
    ['/settings', '', '/?panel=settings'],
    ['/projects', '', '/?panel=settings&tab=projects'],
    ['/runs', '?status=failed', '/?panel=history&status=failed'],
    ['/runs/compare', '?base=a&head=b', '/?panel=compare&base=a&head=b'],
  ])('%s%s → %s', (path, search, expected) => {
    expect(legacyRedirect(path, search)).toBe(expected)
  })
  it('leaves new and unknown routes alone', () => {
    expect(legacyRedirect('/c/abc', '')).toBeNull()
    expect(legacyRedirect('/runs/r1', '')).toBeNull()
    expect(legacyRedirect('/', '?panel=ci')).toBeNull()
  })
})

describe('panels in the query string', () => {
  it('reads a known panel only', () => {
    expect(panelFromSearch('?panel=history')).toBe('history')
    expect(panelFromSearch('?panel=nope')).toBeNull()
    expect(panelFromSearch('')).toBeNull()
  })
  it('opens and closes a panel keeping other params', () => {
    expect(withPanel('?run=1', 'templates')).toBe('?run=1&panel=templates')
    expect(withPanel('?run=1&panel=templates&tab=x', null)).toBe('?run=1')
    expect(withPanel('?panel=compare&base=old&head=new&run=new', null)).toBe('?run=new')
  })
})
