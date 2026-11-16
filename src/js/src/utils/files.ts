/**
 * The files picked in a file input, cleared so picking the same file again
 * fires `change` once more. Copied first: clearing empties the input's FileList.
 */
export function takeFiles(event: Event): File[] {
  const input = event.target
  if (!(input instanceof HTMLInputElement)) return []
  const files = [...(input.files ?? [])]
  input.value = ''
  return files
}
