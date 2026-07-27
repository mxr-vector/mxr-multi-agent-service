import { computed, ref, type Ref } from "vue";
import { FAB_SIZE } from "./useAiChatTriggerPosition";
import { clamp, viewportHeight, viewportWidth } from "../utils/chatViewport";

const PANEL_WIDTH_RATIO = 0.45;
const PANEL_HEIGHT_RATIO = 0.7;
const PANEL_MIN_WIDTH = 360;
const PANEL_MIN_HEIGHT = 480;
const PANEL_VIEWPORT_GAP = 24;
const PANEL_EDGE_MARGIN = 12;
const PANEL_FAB_OFFSET = 16;

export function useAiChatPanelLayout(
  triggerPosition: { x: number; y: number },
  isPanelOpen: Ref<boolean>
) {
  const showHistory = ref<boolean>(true);
  const isMaximized = ref<boolean>(false);
  const responsiveWidth = ref<number>(0);
  const responsiveHeight = ref<number>(0);

  function calcResponsiveSize(): void {
    responsiveWidth.value = Math.max(
      PANEL_MIN_WIDTH,
      Math.floor(viewportWidth() * PANEL_WIDTH_RATIO)
    );
    responsiveHeight.value = Math.max(
      PANEL_MIN_HEIGHT,
      Math.floor(viewportHeight() * PANEL_HEIGHT_RATIO)
    );
  }

  function toggleMaximize(): void {
    isMaximized.value = !isMaximized.value;
  }

  const panelStyle = computed(() => {
    if (isMaximized.value) {
      return {
        width: "100vw",
        height: "100vh",
        left: "0px",
        top: "0px",
      };
    }
    const width = Math.min(responsiveWidth.value, viewportWidth() - PANEL_VIEWPORT_GAP);
    const height = Math.min(responsiveHeight.value, viewportHeight() - PANEL_VIEWPORT_GAP);
    const left = clamp(
      triggerPosition.x + FAB_SIZE - width,
      PANEL_EDGE_MARGIN,
      Math.max(PANEL_EDGE_MARGIN, viewportWidth() - width - PANEL_EDGE_MARGIN)
    );
    const preferredTop = triggerPosition.y - height - PANEL_FAB_OFFSET;
    const fallbackTop = triggerPosition.y + FAB_SIZE + PANEL_FAB_OFFSET;
    const top =
      preferredTop >= PANEL_EDGE_MARGIN
        ? preferredTop
        : clamp(
            fallbackTop,
            PANEL_EDGE_MARGIN,
            Math.max(PANEL_EDGE_MARGIN, viewportHeight() - height - PANEL_EDGE_MARGIN)
          );
    return {
      width: `${width}px`,
      height: `${height}px`,
      left: `${left}px`,
      top: `${top}px`,
    };
  });

  return {
    isPanelOpen,
    showHistory,
    isMaximized,
    responsiveHeight,
    panelStyle,
    calcResponsiveSize,
    toggleMaximize,
  };
}
