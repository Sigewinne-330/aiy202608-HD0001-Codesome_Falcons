/**
 * 图片压缩工具：上传前统一压缩，避免图片过大。
 *
 * 策略：
 *  - 超过 MAX_DIMENSION（默认 1600px）的长边会等比缩到该尺寸（画布缩放）
 *  - 输出为 image/jpeg（质量 0.82），大幅减小体积
 *  - 原图本身很小（长边 ≤ 1600 且 < 500KB）时不压缩，原样返回，避免画质损失
 *  - 返回 Promise<dataUrl>，用法与 FileReader.readAsDataURL 一致
 */
const MAX_DIMENSION = 1600 // 长边上限（px）
const JPEG_QUALITY = 0.82 // JPEG 压缩质量
const SKIP_BYTES = 500 * 1024 // 小于此体积且不需要缩放时跳过压缩

/**
 * 将图片文件压缩为 dataUrl（统一 JPEG 输出）
 * @param {File} file 图片文件
 * @returns {Promise<string>} dataUrl
 */
export function compressImageFile(file) {
  return new Promise((resolve, reject) => {
    if (!file || !file.type || !file.type.startsWith('image/')) {
      return reject(new Error('不是图片文件'))
    }

    const objectUrl = URL.createObjectURL(file)
    const img = new Image()

    img.onload = () => {
      try {
        const needScale = img.width > MAX_DIMENSION || img.height > MAX_DIMENSION
        // 图片够小（尺寸小 + 体积小）→ 直接用原始 dataUrl，不压缩
        if (!needScale && file.size <= SKIP_BYTES) {
          const reader = new FileReader()
          reader.onload = (ev) => {
            URL.revokeObjectURL(objectUrl)
            resolve(ev.target.result)
          }
          reader.onerror = () => {
            URL.revokeObjectURL(objectUrl)
            reject(new Error('读取图片失败'))
          }
          reader.readAsDataURL(file)
          return
        }

        // 需要压缩：画布等比缩放后输出 JPEG
        const scale = needScale
          ? Math.min(MAX_DIMENSION / img.width, MAX_DIMENSION / img.height, 1)
          : 1
        const w = Math.max(1, Math.round(img.width * scale))
        const h = Math.max(1, Math.round(img.height * scale))

        const canvas = document.createElement('canvas')
        canvas.width = w
        canvas.height = h
        const ctx = canvas.getContext('2d')
        // 透明背景填充白色，避免 PNG 转 JPEG 出现黑色底
        ctx.fillStyle = '#ffffff'
        ctx.fillRect(0, 0, w, h)
        ctx.drawImage(img, 0, 0, w, h)

        URL.revokeObjectURL(objectUrl)
        resolve(canvas.toDataURL('image/jpeg', JPEG_QUALITY))
      } catch (e) {
        URL.revokeObjectURL(objectUrl)
        reject(e)
      }
    }

    img.onerror = () => {
      URL.revokeObjectURL(objectUrl)
      reject(new Error('图片加载失败'))
    }

    img.src = objectUrl
  })
}
