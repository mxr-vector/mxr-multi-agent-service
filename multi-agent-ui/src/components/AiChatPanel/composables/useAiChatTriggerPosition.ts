import { computed, reactive, ref, type Ref } from "vue";
import { clamp, viewportHeight, viewportWidth } from "../utils/chatViewport";
import type { AiChatProps } from "../types";

export const FAB_SIZE = 52;
const FOLDED_HANDLE = 18;
const DRAG_THRESHOLD = 4;
const EDGE_SNAP_DISTANCE = 28;

export function useAiChatTriggerPosition(
  props: Readonly<AiChatProps>,
  isPanelOpen: Ref<boolean>,
  togglePanel: () => void | Promise<void>
) {
  const triggerPosition = reactive({ x: 0, y: 0 });
  const isFabDragging = ref<boolean>(false);
  const suppressFabClick = ref<boolean>(false);
  const foldedEdge = ref<"left" | "right" | null>(null);
  let savedFoldedEdge: "left" | "right" | null = null;
  let fabDragState: {
    pointerId: number;
    startClientX: number;
    startClientY: number;
    startX: number;
    startY: number;
    moved: boolean;
  } | null = null;

  function clampFabPosition(): void {
    triggerPosition.x = clamp(triggerPosition.x, 0, Math.max(0, viewportWidth() - FAB_SIZE));
    triggerPosition.y = clamp(triggerPosition.y, 0, Math.max(0, viewportHeight() - FAB_SIZE));
  }

  function initFabPosition(): void {
    triggerPosition.x = viewportWidth() - props.right! - FAB_SIZE;
    triggerPosition.y = viewportHeight() - props.bottom! - FAB_SIZE;
    clampFabPosition();
  }

  function keepFabInViewport(): void {
    triggerPosition.y = clamp(triggerPosition.y, 0, Math.max(0, viewportHeight() - FAB_SIZE));
    if (foldedEdge.value === "left") {
      triggerPosition.x = FOLDED_HANDLE - FAB_SIZE;
      return;
    }
    if (foldedEdge.value === "right") {
      triggerPosition.x = viewportWidth() - FOLDED_HANDLE;
      return;
    }
    clampFabPosition();
  }

  function handleFabPointerDown(event: PointerEvent): void {
    if (event.button !== 0) return;
    if (foldedEdge.value) {
      foldedEdge.value = null;
      clampFabPosition();
    }
    fabDragState = {
      pointerId: event.pointerId,
      startClientX: event.clientX,
      startClientY: event.clientY,
      startX: triggerPosition.x,
      startY: triggerPosition.y,
      moved: false,
    };
    window.addEventListener("pointermove", handleFabPointerMove);
    window.addEventListener("pointerup", handleFabPointerUp);
  }

  function handleFabPointerMove(event: PointerEvent): void {
    if (!fabDragState || event.pointerId !== fabDragState.pointerId) return;
    const dx = event.clientX - fabDragState.startClientX;
    const dy = event.clientY - fabDragState.startClientY;
    if (!fabDragState.moved && Math.hypot(dx, dy) < DRAG_THRESHOLD) return;
    fabDragState.moved = true;
    isFabDragging.value = true;
    triggerPosition.x = fabDragState.startX + dx;
    triggerPosition.y = fabDragState.startY + dy;
    clampFabPosition();
  }

  function handleFabMouseEnter(): void {
    if (foldedEdge.value && !isPanelOpen.value) {
      savedFoldedEdge = foldedEdge.value;
      foldedEdge.value = null;
      clampFabPosition();
    }
  }

  function handleFabMouseLeave(): void {
    if (savedFoldedEdge && !isPanelOpen.value) {
      foldedEdge.value = savedFoldedEdge;
      if (savedFoldedEdge === "left") {
        triggerPosition.x = FOLDED_HANDLE - FAB_SIZE;
      } else {
        triggerPosition.x = viewportWidth() - FOLDED_HANDLE;
      }
    }
    savedFoldedEdge = null;
  }

  function handleFabPointerUp(event: PointerEvent): void {
    if (!fabDragState || event.pointerId !== fabDragState.pointerId) return;
    const wasDragging = fabDragState.moved;
    fabDragState = null;
    window.removeEventListener("pointermove", handleFabPointerMove);
    window.removeEventListener("pointerup", handleFabPointerUp);
    if (wasDragging) {
      suppressFabClick.value = true;
      settleFabPosition();
      setTimeout(() => {
        suppressFabClick.value = false;
      }, 0);
    }
    isFabDragging.value = false;
  }

  function settleFabPosition(): void {
    clampFabPosition();
    if (triggerPosition.x <= EDGE_SNAP_DISTANCE) {
      triggerPosition.x = FOLDED_HANDLE - FAB_SIZE;
      foldedEdge.value = "left";
      return;
    }
    const rightDistance = viewportWidth() - (triggerPosition.x + FAB_SIZE);
    if (rightDistance <= EDGE_SNAP_DISTANCE) {
      triggerPosition.x = viewportWidth() - FOLDED_HANDLE;
      foldedEdge.value = "right";
    }
  }

  function handleFabClick(): void {
    if (suppressFabClick.value) return;
    if (foldedEdge.value) {
      foldedEdge.value = null;
      clampFabPosition();
    }
    savedFoldedEdge = null;
    void togglePanel();
  }

  function cleanupTrigger(): void {
    window.removeEventListener("pointermove", handleFabPointerMove);
    window.removeEventListener("pointerup", handleFabPointerUp);
  }

  const triggerStyle = computed(() => ({
    left: `${triggerPosition.x}px`,
    top: `${triggerPosition.y}px`,
  }));

  const triggerClasses = computed(() => ({
    "is-dragging": isFabDragging.value,
    "is-folded-left": foldedEdge.value === "left",
    "is-folded-right": foldedEdge.value === "right",
  }));

  return {
    triggerPosition,
    isFabDragging,
    triggerStyle,
    triggerClasses,
    initFabPosition,
    keepFabInViewport,
    handleFabPointerDown,
    handleFabClick,
    handleFabMouseEnter,
    handleFabMouseLeave,
    cleanupTrigger,
  };
}
