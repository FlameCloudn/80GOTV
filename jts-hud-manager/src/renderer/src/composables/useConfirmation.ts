import { ref } from 'vue';

// Singleton state — shared across all callers
const isOpen = ref(false);
const message = ref('');
const confirmLabel = ref('删除');
const secondaryLabel = ref<string | null>(null);
let resolveCallback: ((value: boolean) => void) | null = null;
let resolveChoiceCallback: ((value: 'primary' | 'secondary' | null) => void) | null = null;

export function useConfirmation() {
  // Simple boolean confirm (existing behaviour)
  const confirm = (msg: string, label = '删除'): Promise<boolean> => {
    message.value = msg;
    confirmLabel.value = label;
    secondaryLabel.value = null;
    isOpen.value = true;

    return new Promise((resolve) => {
      resolveCallback = resolve;
    });
  };

  // Tri-choice confirm — returns 'primary', 'secondary', or null (cancelled)
  const confirmChoice = (msg: string, primary: string, secondary: string): Promise<'primary' | 'secondary' | null> => {
    message.value = msg;
    confirmLabel.value = primary;
    secondaryLabel.value = secondary;
    isOpen.value = true;

    return new Promise((resolve) => {
      resolveChoiceCallback = resolve;
    });
  };

  const onConfirm = () => {
    isOpen.value = false;
    resolveCallback?.(true);
    resolveCallback = null;
    resolveChoiceCallback?.('primary');
    resolveChoiceCallback = null;
  };

  const onSecondary = () => {
    isOpen.value = false;
    resolveChoiceCallback?.('secondary');
    resolveChoiceCallback = null;
  };

  const onCancel = () => {
    isOpen.value = false;
    resolveCallback?.(false);
    resolveCallback = null;
    resolveChoiceCallback?.(null);
    resolveChoiceCallback = null;
  };

  return { isOpen, message, confirmLabel, secondaryLabel, confirm, confirmChoice, onConfirm, onSecondary, onCancel };
}
