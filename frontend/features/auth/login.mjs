(function () {
      document.getElementById('themeButton').addEventListener('click', function () {
        var current = document.documentElement.getAttribute('data-theme');
        var next = current === 'dark' ? 'light' : 'dark';
        document.documentElement.setAttribute('data-theme', next);
        localStorage.setItem('theme', next);
      });

      document.querySelectorAll('[data-password-target]').forEach(function (button) {
        button.addEventListener('click', function () {
          var input = document.getElementById(button.getAttribute('data-password-target'));
          var show = input.type === 'password';
          input.type = show ? 'text' : 'password';
          // 换图标（睁眼 ↔ 划掉的眼），提示文字跟着变
          button.classList.toggle('is-shown', show);
          button.setAttribute('aria-label', show ? window.siteMessage('client.inline_login.hide_password') : window.siteMessage('client.inline_login.show_password'));
          button.setAttribute('title', show ? window.siteMessage('client.inline_login.hide_password') : window.siteMessage('client.inline_login.show_password'));
        });
      });

      var emailInput = document.getElementById('registerEmail');
      var emailCodeInput = document.getElementById('registerEmailCode');
      var sendEmailButton = document.getElementById('sendEmailCode');
      var verifyEmailButton = document.getElementById('verifyEmailCode');
      var emailStatus = document.getElementById('emailStatus');
      var registerForm = document.getElementById('registerForm');
      var registerSubmitStatus = document.getElementById('registerSubmitStatus');
      var groupUsernameField = document.getElementById('registerGroupUsernameField');
      var groupUsernameInput = document.getElementById('registerGroupUsername');
      function syncRegistrationSchoolFields() {
        if (!registerForm || !groupUsernameField || !groupUsernameInput) return;
        var selected = registerForm.querySelector('input[name="is_bashizhong_student"]:checked');
        var student = selected && selected.value === '1';
        groupUsernameField.hidden = !student;
        groupUsernameInput.required = !!student;
      }
      if (registerForm) {
        registerForm.querySelectorAll('input[name="is_bashizhong_student"]').forEach(function (radio) {
          radio.addEventListener('change', syncRegistrationSchoolFields);
        });
        syncRegistrationSchoolFields();
      }
      if (emailInput && emailStatus) {
        emailInput.addEventListener('input', function () {
          var verified = (emailInput.dataset.verifiedEmail || '').toLowerCase();
          if (verified && emailInput.value.trim().toLowerCase() !== verified) {
            emailStatus.textContent = window.siteMessage('client.inline_login.the_email_changed_send_and_verify');
            emailStatus.className = 'email-status error';
          }
        });
      }

      // 发送 / 验证失败：对应输入框标红，原因用右上角提示（下面的状态行不再写红字，重新输入时去掉红框）
      function showEmailError(input, message) {
        emailStatus.textContent = '';
        emailStatus.className = 'email-status';
        input.setAttribute('aria-invalid', 'true');
        input.addEventListener('input', function () { input.removeAttribute('aria-invalid'); }, { once: true });
        window.showToast(message, 'error', { key: 'register-email' });
      }

      function applyCsrfToken(token) {
        document.querySelectorAll('input[name="csrf_token"]').forEach(function (input) {
          input.value = token;
        });
        return token;
      }

      function refreshCsrfToken() {
        return fetch('/auth/csrf-token', {
          credentials: 'same-origin',
          cache: 'no-store',
          headers: {'X-Requested-With': 'XMLHttpRequest'}
        }).then(function (response) {
          return response.json().then(function (data) {
            if (!response.ok || !data.csrf_token) {
              throw new Error(window.siteMessage('client.inline_login.could_not_refresh_the_page_security'));
            }
            return applyCsrfToken(data.csrf_token);
          });
        });
      }

      function emailRequest(path, values, retried) {
        var csrf = document.querySelector('form[action="/register"] input[name="csrf_token"]');
        values.set('csrf_token', csrf ? csrf.value : '');
        return fetch(path, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8',
            'X-Requested-With': 'XMLHttpRequest'
          },
          body: values.toString()
        }).then(function (response) {
          return response.json().then(function (data) {
            if (response.status === 403 && !retried && /CSRF/i.test(data.error || '')) {
              return refreshCsrfToken().then(function () {
                return emailRequest(path, values, true);
              });
            }
            if (!response.ok) throw new Error(data.error || window.siteMessage('client.inline_login.something_went_wrong_please_try_again'));
            return data;
          });
        });
      }

      if (registerForm) {
        registerForm.addEventListener('submit', function (event) {
          event.preventDefault();
          if (registerForm.dataset.submitting === '1') return;
          registerForm.dataset.submitting = '1';
          var submitButton = registerForm.querySelector('button[type="submit"]');
          if (submitButton) {
            submitButton.disabled = true;
            submitButton.textContent = window.siteMessage('client.inline_login.submitting');
          }
          if (registerSubmitStatus) {
            registerSubmitStatus.textContent = window.siteMessage('client.inline_login.submitting_your_application_please_do_not');
            registerSubmitStatus.className = 'email-status';
          }

          var sent = false;
          function submitNow() {
            if (sent) return;
            sent = true;
            window.clearTimeout(fallbackTimer);
            HTMLFormElement.prototype.submit.call(registerForm);
          }
          var fallbackTimer = window.setTimeout(submitNow, 3500);
          refreshCsrfToken().then(submitNow).catch(submitNow);
        });
      }

      if (sendEmailButton) {
        sendEmailButton.addEventListener('click', function () {
          var email = emailInput.value.trim();
          if (!email || !emailInput.checkValidity()) {
            emailInput.reportValidity();
            return;
          }
          sendEmailButton.disabled = true;
          emailStatus.textContent = window.siteMessage('client.inline_login.sending');
          emailStatus.className = 'email-status';
          emailRequest('/auth/email/send-code', new URLSearchParams({email: email}))
            .then(function (data) {
              emailStatus.textContent = data.message;
              emailStatus.className = 'email-status success';
              var seconds = 60;
              sendEmailButton.textContent = window.siteMessage('client.inline_login.resend_in_seconds_s', {seconds: seconds});
              var timer = setInterval(function () {
                seconds -= 1;
                sendEmailButton.textContent = window.siteMessage('client.inline_login.resend_in_seconds_s', {seconds: seconds});
                if (seconds <= 0) {
                  clearInterval(timer);
                  sendEmailButton.disabled = false;
                  sendEmailButton.textContent = window.siteMessage('client.inline_login.resend');
                }
              }, 1000);
            })
            .catch(function (error) {
              sendEmailButton.disabled = false;
              showEmailError(emailInput, error.message);
            });
        });
      }

      if (verifyEmailButton) {
        verifyEmailButton.addEventListener('click', function () {
          verifyEmailButton.disabled = true;
          emailRequest('/auth/email/verify-code', new URLSearchParams({
            email: emailInput.value.trim(),
            code: emailCodeInput.value.trim()
          })).then(function (data) {
            emailInput.dataset.verifiedEmail = emailInput.value.trim().toLowerCase();
            emailStatus.textContent = data.message;
            emailStatus.className = 'email-status success';
            verifyEmailButton.textContent = window.siteMessage('client.inline_login.verified');
          }).catch(function (error) {
            verifyEmailButton.disabled = false;
            showEmailError(emailCodeInput, error.message);
          });
        });
      }

    })();

    function reloadCaptcha() {
      fetch('/captcha/reload')
        .then(function () {
          var loginCaptcha = document.getElementById('captchaImage');
          var registerCaptcha = document.getElementById('captchaImageReg');
          var source = '/captcha/image?t=' + Date.now();
          if (loginCaptcha) loginCaptcha.src = source;
          if (registerCaptcha) registerCaptcha.src = source;
        });
    }

document.querySelectorAll('[data-reload-captcha]').forEach((button) => {
  button.addEventListener('click', reloadCaptcha);
});
