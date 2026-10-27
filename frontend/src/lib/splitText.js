const CHARS = /([^\s-])/g

function wrapChars(node) {
  const text = node.textContent
  const frag = document.createDocumentFragment()
  const words = text.split(/(\s+)/)

  words.forEach((word) => {
    if (/^\s+$/.test(word)) {
      frag.appendChild(document.createTextNode(word))
      return
    }
    const wordEl = document.createElement('span')
    wordEl.className = 'split-word inline-block whitespace-nowrap'
    const chars = word.match(CHARS)
    chars.forEach((ch) => {
      const charEl = document.createElement('span')
      charEl.className = 'split-char inline-block'
      charEl.textContent = ch
      wordEl.appendChild(charEl)
    })
    frag.appendChild(wordEl)
    frag.appendChild(document.createTextNode(' '))
  })

  node.parentNode.replaceChild(frag, node)
}

/**
 * Splits an element's text into per-character spans wrapped in an
 * overflow-hidden mask, with the content pre-translated 110% below the mask
 * (the hidden state). Idempotent: re-invoking on an already-split element
 * simply returns the existing mask/content references.
 *
 * Returns { mask, content } or null when no element is given.
 */
export function splitText(element) {
  if (!element) return null

  const existingMask = element.querySelector('.clip-mask')
  const existingContent = element.querySelector('.split-content')
  if (element.dataset.split === 'true' && existingMask && existingContent) {
    return { mask: existingMask, content: existingContent }
  }

  const mask = document.createElement('div')
  mask.className = 'clip-mask'
  mask.style.display = 'block'
  mask.style.position = 'relative'

  const content = document.createElement('div')
  content.className = 'split-content'
  content.style.display = 'block'
  content.style.willChange = 'transform'
  content.style.transform = 'translateY(110%)'

  while (element.firstChild) {
    content.appendChild(element.firstChild)
  }

  Array.from(content.childNodes).forEach((node) => {
    if (node.nodeType === Node.TEXT_NODE && node.textContent.trim()) {
      wrapChars(node)
    }
  })

  mask.appendChild(content)
  element.appendChild(mask)
  element.dataset.split = 'true'
  element.classList.add('split-line')

  return { mask, content }
}
