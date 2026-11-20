(function () {
    // 八十中学生才需要填群内昵称；勾选“创建账号”才需要填 Steam ID 和初始密码（和后端校验一致）
    var form = document.getElementById('playerForm');
    var groupField = document.getElementById('groupUsernameField');
    var groupInput = groupField && groupField.querySelector('input');
    var steamInput = document.getElementById('steamIdInput');
    function syncSchoolFields() {
      var checked = form.querySelector('input[name="is_bashizhong_student"]:checked');
      var student = checked && checked.value === '1';
      if (groupField) groupField.hidden = !student;
      if (groupInput) groupInput.required = !!student;
    }
    form.querySelectorAll('input[name="is_bashizhong_student"]').forEach(function (radio) {
      radio.addEventListener('change', syncSchoolFields);
    });
    syncSchoolFields();

    var createAccount = document.getElementById('createAccount');
    var accountFields = document.getElementById('accountFields');
    function syncAccountFields() {
      if (!createAccount || !accountFields) return;
      accountFields.hidden = !createAccount.checked;
      accountFields.querySelectorAll('input[type="password"]').forEach(function (input) {
        input.required = createAccount.checked;
      });
      if (steamInput) steamInput.required = createAccount.checked;
    }
    if (createAccount) {
      createAccount.addEventListener('change', syncAccountFields);
      syncAccountFields();
    }
  })();
