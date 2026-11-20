import { csrfToken, legacyAjax } from '../../shared/site-http.mjs';

(function(){
  var dialog = document.getElementById('fbOverlay');
  var opener = document.getElementById('fbBtn');
  var closeButton = document.getElementById('fbClose');
  var form = document.getElementById('fbForm');
  var contentInput = document.getElementById('fbContent');
  var submitButton = document.getElementById('fbSubmit');
  var submitting = false;

  function closeFeedback(){
    if (dialog.open) dialog.close();
  }

  opener.addEventListener('click', function(){
    opener.setAttribute('aria-expanded', 'true');
    dialog.showModal();
    document.getElementById('fbType').focus();
  });
  closeButton.addEventListener('click', closeFeedback);
  contentInput.addEventListener('input', function(){
    if (contentInput.value.trim().length >= 2) contentInput.removeAttribute('aria-invalid');
  });
  dialog.addEventListener('click', function(event){
    if (event.target === dialog) closeFeedback();
  });
  dialog.addEventListener('close', function(){
    opener.setAttribute('aria-expanded', 'false');
    opener.focus();
  });

  form.addEventListener('submit', function(event){
    event.preventDefault();
    if(submitting) return;
    var content = contentInput.value.trim();
    if(content.length < 2){
      // 字段标红、光标放回去，右上角提示原因（写的内容不动）
      contentInput.setAttribute('aria-invalid', 'true');
      contentInput.focus();
      window.showToast(window.siteMessage('client.inline_public.write_at_least_2_characters'), 'error', { key: 'feedback' });
      return;
    }
    submitting = true;
    submitButton.textContent = window.siteMessage('client.inline_public.submitting');
    submitButton.disabled = true;

    legacyAjax('/api/feedback/submit', {
      method:'POST',
      headers:{
        'Content-Type':'application/json',
        'X-CSRF-Token': csrfToken(),
        'X-Requested-With': 'XMLHttpRequest'
      },
      body: JSON.stringify({
        type: document.getElementById('fbType').value,
        content: content,
        contact: document.getElementById('fbContact').value.trim(),
        page_url: location.href
      })
    }).then(function(response){ return response.json(); }).then(function(data){
      if(!data.ok){
        // 没保存：内容留在框里，可以直接再点提交
        window.showToast(data.error || window.siteMessage('client.inline_public.submission_failed'), 'error', { key: 'feedback' });
        return;
      }
      window.dismissToast('feedback', true);
      closeFeedback();
      form.reset();
      window.showToast(window.siteMessage('client.inline_public.thanks_for_the_feedback'), 'success');
    }).catch(function(){
      window.showToast(window.siteMessage('client.inline_public.network_error_please_try_again'), 'error', { key: 'feedback' });
    }).finally(function(){
      submitting = false;
      submitButton.textContent=window.siteMessage('client.inline_public.submit');
      submitButton.disabled=false;
    });
  });
})();
