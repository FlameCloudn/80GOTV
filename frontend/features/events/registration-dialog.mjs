var regDialog = document.getElementById('regOverlay');
var regOpenButton = document.getElementById('regOpenButton');
function showRegForm(){
  if (!regDialog.open) regDialog.showModal();
  regOpenButton.setAttribute('aria-expanded', 'true');
  document.getElementById('regTeamName').focus();
}
function hideRegForm(){
  if (regDialog.open) regDialog.close();
}
regDialog.addEventListener('click', function(event){
  if (event.target === regDialog) hideRegForm();
});
regDialog.addEventListener('close', function(){
  regOpenButton.setAttribute('aria-expanded', 'false');
  regOpenButton.focus();
});
function selectSlot(n){
  document.querySelectorAll('#slotSelector .event-modal-slot-opt').forEach((el,i)=>{
    el.classList.toggle('is-selected', i===n);
  });
  document.querySelectorAll('.slot-label').forEach((el,i)=>{el.textContent = i===n ? window.siteMessage('client.inline_event_detail.you') : ''});
  document.querySelector('input[name="my_slot"][value="'+n+'"]').checked = true;
  document.querySelectorAll('#regOverlay input[name^="pname_"]').forEach((input,i)=>{
    const label = i===n ? window.siteMessage('client.inline_event_detail.your_nickname') : window.siteMessage('client.inline_event_detail.player_value1_nickname_optional', {value1: (i+1)});
    input.placeholder = label;
  });
}

regOpenButton?.addEventListener('click', showRegForm);
regDialog?.querySelectorAll('[data-registration-close]').forEach(button => button.addEventListener('click', hideRegForm));
regDialog?.querySelectorAll('[data-registration-slot]').forEach((input) => {
  input.addEventListener('change', () => selectSlot(Number(input.value)));
});
