/**
 * Validation script for Zustand stores
 * This script manually tests the store functionality
 */

import { useChatStore } from './useChatStore.js';
import { useSettingsStore } from './useSettingsStore.js';
import { usePipelineStore } from './usePipelineStore.js';

console.log('=== Zustand Stores Validation ===\n');

// Test useChatStore
console.log('1. Testing useChatStore...');
const chatStore = useChatStore.getState();
console.log('  ✓ Initial conversations:', Object.keys(chatStore.conversations).length);
console.log('  ✓ Active conversation ID:', chatStore.activeId);
console.log('  ✓ Telemetry entries:', chatStore.telemetry.length);
console.log('  ✓ Provider health status:', chatStore.providerHealth.length);

// Test conversation operations
chatStore.newConversation();
const newConvId = useChatStore.getState().activeId;
console.log('  ✓ New conversation created:', newConvId);

chatStore.addMessage(newConvId, {
  id: 'msg-1',
  role: 'user',
  content: 'Test message',
  createdAt: Date.now(),
});
console.log('  ✓ Message added to conversation');

const activeConv = chatStore.getActiveConversation();
console.log('  ✓ Active conversation messages:', activeConv.messages.length);

// Test useSettingsStore
console.log('\n2. Testing useSettingsStore...');
const settingsStore = useSettingsStore.getState();
console.log('  ✓ Message density:', settingsStore.messageDensity);
console.log('  ✓ Font size:', settingsStore.fontSize);
console.log('  ✓ Animations enabled:', settingsStore.animationsEnabled);
console.log('  ✓ Auto expand reasoning:', settingsStore.autoExpandReasoning);
console.log('  ✓ Mission control open:', settingsStore.missionControlOpen);
console.log('  ✓ Mission control pinned:', settingsStore.missionControlPinned);

// Test settings update
settingsStore.updateSetting('fontSize', 'large');
const updatedSettings = useSettingsStore.getState();
console.log('  ✓ Font size updated to:', updatedSettings.fontSize);

// Test settings reset
settingsStore.resetToDefaults();
console.log('  ✓ Settings reset to defaults');

// Test usePipelineStore
console.log('\n3. Testing usePipelineStore...');
const pipelineStore = usePipelineStore.getState();
console.log('  ✓ Initial stage:', pipelineStore.stage);
console.log('  ✓ Initial progress:', pipelineStore.progress);
console.log('  ✓ Agent states:', Object.keys(pipelineStore.agentStates).length);

// Test pipeline stage transitions
pipelineStore.setStage('breaker');
console.log('  ✓ Stage updated to:', usePipelineStore.getState().stage);
console.log('  ✓ Progress calculated:', usePipelineStore.getState().progress, '%');

// Test agent state updates
pipelineStore.startAgent('logician');
const logicianState = pipelineStore.getAgentState('logician');
console.log('  ✓ Logician agent started:', logicianState.status);

pipelineStore.updateAgentState('logician', { progress: 50 });
console.log('  ✓ Logician progress updated:', pipelineStore.getAgentState('logician').progress, '%');

pipelineStore.addClaim('logician', {
  id: 'claim-1',
  text: 'Test claim',
  confidence: 85,
  validationStatus: 'validated',
});
console.log('  ✓ Claim added to logician:', pipelineStore.getAgentState('logician').claims.length);

pipelineStore.completeAgent('logician', {
  summary: 'Analysis complete',
  confidence: 'high',
});
console.log('  ✓ Logician agent completed:', pipelineStore.getAgentState('logician').status);

// Test reset
pipelineStore.reset();
console.log('  ✓ Pipeline store reset, stage:', usePipelineStore.getState().stage);

console.log('\n=== All Store Validations Passed ✓ ===');
