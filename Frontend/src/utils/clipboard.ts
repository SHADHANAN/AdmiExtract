/**
 * Reliable clipboard copy utility with modern Clipboard API and fallback.
 * Works across secure contexts (HTTPS) and non-secure HTTP LAN environments.
 */
export async function copyToClipboard(text: string): Promise<boolean> {
  // 1. Try modern Clipboard API if available
  if (typeof navigator !== 'undefined' && navigator.clipboard && typeof navigator.clipboard.writeText === 'function') {
    try {
      await navigator.clipboard.writeText(text)
      return true
    } catch (clipboardErr) {
      console.warn('navigator.clipboard.writeText failed, falling back to textarea execCommand:', clipboardErr)
    }
  }

  // 2. Fallback for insecure contexts (e.g. HTTP over LAN IP) or legacy browsers
  try {
    const textarea = document.createElement('textarea')
    textarea.value = text
    textarea.style.position = 'fixed'
    textarea.style.opacity = '0'
    document.body.appendChild(textarea)
    textarea.focus()
    textarea.select()
    const successful = document.execCommand('copy')
    document.body.removeChild(textarea)

    if (!successful) {
      throw new Error('document.execCommand copy failed')
    }
    return true
  } catch (fallbackErr) {
    console.error('Fallback copyToClipboard failed:', fallbackErr)
    throw fallbackErr
  }
}
