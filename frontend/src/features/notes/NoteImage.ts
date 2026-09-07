import Image from "@tiptap/extension-image";
import { mergeAttributes } from "@tiptap/react";
import { assetPreviewUrl } from "@/api/domains/assets";
import { nodeButton, nodeIcon, nodeLabels } from "./noteNodeUI";

// Only resolve authenticated URLs for display; keep stable references in saved content.
export function noteImageUrl(src: string): string {
  const asset = /^mosael-asset:([a-zA-Z0-9-]+)$/.exec(src);
  if (asset) return assetPreviewUrl(asset[1]);
  return /^(https?:\/\/|data:image\/(?:png|jpeg|webp|gif);base64,)/i.test(src)
    ? src
    : "";
}
export function createNoteImage(locale: string) {
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
        const img = document.createElement("img");
        img.loading = "lazy";
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
        dom.append(img, unavailable, form);
        function reset() {
          source.value = String(node.attrs.src || "");
          alt.value = String(node.attrs.alt || "");
          source.setCustomValidity("");
        }
        function render() {
          const src = noteImageUrl(String(node.attrs.src || ""));
          if (img.getAttribute("src") !== src) {
            img.src = src;
            unavailable.hidden = !!src;
            img.hidden = !src;
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
        img.onerror = () => {
          unavailable.hidden = false;
          img.hidden = true;
        };
        img.onload = () => {
          unavailable.hidden = true;
          img.hidden = false;
        };
        const select = () => {
          const pos = getPos();
          if (editor.isEditable && typeof pos === "number") {
            editor.commands.setNodeSelection(pos);
            show();
          }
        };
        img.onclick = select;
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
          stopEvent: (event) => form.contains(event.target as globalThis.Node),
          ignoreMutation: (mutation) => mutation.type !== "selection",
          destroy() {
            img.onload = img.onerror = img.onclick = null;
          },
        };
      };
    },
  }).configure({ allowBase64: true });
}
