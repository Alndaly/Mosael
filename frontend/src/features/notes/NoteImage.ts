import Image from "@tiptap/extension-image";
import { mergeAttributes } from "@tiptap/react";
import type { Node as ProseMirrorNode } from "@tiptap/pm/model";
import { assetPreviewUrl } from "@/api/domains/assets";
import { requestImagePreview } from "@/components/app/image-preview-request";
import type { ImagePreviewItem } from "@/components/app/image-preview";
import { nodeButton, nodeIcon, nodeLabels } from "./noteNodeUI";

// Only resolve authenticated URLs for display; keep stable references in saved content.
export function noteImageUrl(src: string): string {
  const asset = /^mosael-asset:([a-zA-Z0-9-]+)$/.exec(src);
  if (asset) return assetPreviewUrl(asset[1]);
  return /^(https?:\/\/|data:image\/(?:png|jpeg|webp|gif);base64,)/i.test(src)
    ? src
    : "";
}
/**
 * 这篇笔记里的全部图片,按在正文里的先后 —— 点开一张,灯箱里左右翻的就是它们。显示不出来的(地址不认)不进来。
 * 标题用替代文字;没写的按「笔记图片 n」(n 是它在这一组里的序号)。
 */
export function noteImageGallery(doc: ProseMirrorNode, untitled: (n: number) => string): ImagePreviewItem[] {
  const gallery: ImagePreviewItem[] = [];
  doc.descendants((node) => {
    if (node.type.name !== "image") return true;
    const src = noteImageUrl(String(node.attrs.src || ""));
    if (src) gallery.push({ src, title: String(node.attrs.alt || node.attrs.title || "") || untitled(gallery.length + 1) });
    return false;
  });
  return gallery;
}

/**
 * `preview`:图上压一颗「看大图」(悬停、键盘走到时露出来)。编辑时点图的意思是「选中它去改链接」,所以看大图
 * 是另一颗按钮;只读时点图本身也开。画板上的笔记卡片不给 —— 那里整块不接指针,点它是选中格子。
 */
export function createNoteImage(locale: string, { preview = false }: { preview?: boolean } = {}) {
  const labels = nodeLabels(locale);
  return Image.extend({
    renderHTML({ HTMLAttributes }) {
      const src = String(HTMLAttributes.src || "");
      return [
        "img",
        mergeAttributes(HTMLAttributes, {
          src: src.startsWith("mosael-asset:") ? src : noteImageUrl(src),
        }),
      ];
    },
    addNodeView() {
      return ({ node: initial, editor, getPos }) => {
        let node = initial;
        const dom = document.createElement("figure");
        dom.className = "note-image-node";
        //: 图和「看大图」装在一个按图片大小收紧的框里:按钮压在**图**的角上,而不是整行的角上(图是居中的)。
        const frame = document.createElement("span");
        frame.className = "note-image-frame";
        const img = document.createElement("img");
        img.loading = "lazy";
        frame.append(img);
        const zoom = preview ? nodeButton(labels.preview, "expand") : null;
        if (zoom) {
          zoom.classList.add("note-image-zoom");
          frame.append(zoom);
        }
        const unavailable = document.createElement("div");
        unavailable.className = "note-image-unavailable";
        unavailable.textContent = labels.unavailable;
        unavailable.hidden = true;
        const form = document.createElement("form");
        form.className = "note-image-edit";
        form.hidden = true;
        form.contentEditable = "false";
        const row = document.createElement("div");
        row.className = "note-image-link-row";
        row.append(nodeIcon("link"));
        const source = document.createElement("input");
        source.type = "text";
        source.spellcheck = false;
        source.setAttribute("aria-label", labels.imageLink);
        source.placeholder = "https://";
        const apply = nodeButton(labels.apply, "check");
        apply.type = "submit";
        const cancel = nodeButton(labels.cancel, "close");
        const altLabel = document.createElement("label");
        altLabel.className = "note-image-alt";
        altLabel.textContent = labels.alt;
        const alt = document.createElement("input");
        alt.type = "text";
        alt.setAttribute("aria-label", labels.alt);
        altLabel.append(alt);
        row.append(source, apply, cancel);
        form.append(row, altLabel);
        dom.append(frame, unavailable, form);
        function reset() {
          source.value = String(node.attrs.src || "");
          alt.value = String(node.attrs.alt || "");
          source.setCustomValidity("");
        }
        //: 图显示不出来时,连同压在它上面的「看大图」一起收起(框跟着图走)。
        function showImage(visible: boolean) {
          img.hidden = !visible;
          frame.hidden = !visible;
          unavailable.hidden = visible;
        }
        function render() {
          const src = noteImageUrl(String(node.attrs.src || ""));
          if (img.getAttribute("src") !== src) {
            img.src = src;
            showImage(!!src);
          }
          img.alt = String(node.attrs.alt || "");
          img.title = String(node.attrs.title || "");
          if (!form.contains(document.activeElement)) reset();
        }
        function show() {
          if (editor.isEditable) {
            reset();
            form.hidden = false;
            dom.classList.add("is-selected");
          }
        }
        function hide() {
          form.hidden = true;
          dom.classList.remove("is-selected");
          reset();
        }
        img.onerror = () => showImage(false);
        img.onload = () => showImage(true);
        const select = () => {
          const pos = getPos();
          if (editor.isEditable && typeof pos === "number") {
            editor.commands.setNodeSelection(pos);
            show();
          }
        };
        const openPreview = (from: HTMLElement) => {
          const src = noteImageUrl(String(node.attrs.src || ""));
          if (!src) return;
          const gallery = noteImageGallery(editor.state.doc, labels.previewOf);
          const self = gallery.find((item) => item.src === src);
          requestImagePreview(from, { src, title: self?.title, gallery });
        };
        if (zoom) {
          zoom.onclick = (event) => {
            event.preventDefault();
            openPreview(zoom);
          };
        }
        //: 只读时点图没有别的意思(改不了链接),直接开大图。
        img.onclick = () => (preview && !editor.isEditable ? openPreview(img) : select());
        unavailable.onclick = select;
        source.oninput = () => source.setCustomValidity("");
        form.onsubmit = (event) => {
          event.preventDefault();
          const src = source.value.trim();
          if (!src || !noteImageUrl(src)) {
            source.setCustomValidity(labels.invalid);
            source.reportValidity();
            return;
          }
          const pos = getPos();
          if (!editor.isEditable || typeof pos !== "number") return;
          editor.view.dispatch(
            editor.state.tr.setNodeMarkup(pos, undefined, {
              ...node.attrs,
              src,
              alt: alt.value,
            }),
          );
          hide();
          editor.view.focus();
        };
        cancel.onclick = () => {
          hide();
          editor.view.focus();
        };
        form.onkeydown = (event) => {
          if (event.key === "Escape") {
            event.preventDefault();
            event.stopPropagation();
            hide();
            editor.view.focus();
          }
        };
        render();
        return {
          dom,
          update(next) {
            if (next.type !== node.type) return false;
            node = next;
            render();
            return true;
          },
          selectNode: show,
          deselectNode: hide,
          //: 「看大图」上的按下、点击都不交给编辑器 —— 交过去的话,按下那一刻图就被选中、改链接的表单弹了出来。
          stopEvent: (event) => form.contains(event.target as globalThis.Node) || Boolean(zoom?.contains(event.target as globalThis.Node)),
          ignoreMutation: (mutation) => mutation.type !== "selection",
          destroy() {
            img.onload = img.onerror = img.onclick = null;
            if (zoom) zoom.onclick = null;
          },
        };
      };
    },
  }).configure({ allowBase64: true });
}
