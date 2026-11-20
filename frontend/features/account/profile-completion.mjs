(function () {
    var form = document.getElementById('profileCompletionForm');
    var group = document.getElementById('profileCompletionGroup');
    if (!form || !group) return;
    var groupInput = group.querySelector('input');
    function syncCompletionFields() {
      var checked = form.querySelector('input[name="is_bashizhong_student"]:checked');
      var student = checked && checked.value === '1';
      group.hidden = !student;
      groupInput.required = !!student;
      if (student) groupInput.focus();
    }
    form.querySelectorAll('input[name="is_bashizhong_student"]').forEach(function (radio) {
      radio.addEventListener('change', syncCompletionFields);
    });
    syncCompletionFields();
    var firstChoice = form.querySelector('input[name="is_bashizhong_student"]');
    if (!form.querySelector('input[name="is_bashizhong_student"]:checked') && firstChoice) {
      firstChoice.focus();
    }
  })();
