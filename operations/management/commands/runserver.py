from django.core.management import call_command
from django.core.management.commands.runserver import Command as RunserverCommand


class Command(RunserverCommand):
    help = 'Starts a lightweight web server for development and auto-applies migrations first.'

    def inner_run(self, *args, **options):
        self.stdout.write(self.style.NOTICE('Applying migrations before starting development server...'))
        call_command('migrate', interactive=False, verbosity=0)
        return super().inner_run(*args, **options)
