function compact(value: number) {
  return Number(value.toFixed(2))
}

export function trendPath(values: number[], width: number, height: number, padding: number, sharedMax?: number) {
  if (!values.length) return ''
  const max = Math.max(1, sharedMax ?? Math.max(...values))
  const plotWidth = width - padding * 2
  const plotHeight = height - padding * 2
  const steps = Math.max(1, values.length - 1)

  const points = values.map((value, index) => {
      const x = padding + (index / steps) * plotWidth
      const y = padding + (1 - Math.max(0, value) / max) * plotHeight
      return { x: compact(x), y: compact(y) }
    })

  return points.slice(1).reduce((path, point, index) => {
    const previous = points[index]
    const controlX = compact((previous.x + point.x) / 2)
    return `${path} C ${controlX} ${previous.y} ${controlX} ${point.y} ${point.x} ${point.y}`
  }, `M ${points[0].x} ${points[0].y}`)
}
