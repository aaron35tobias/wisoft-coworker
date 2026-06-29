from django.core.management.base import BaseCommand

from page_speed_and_cwv.ai_evaluator import evaluate_website_latest_vs_previous

class Command(BaseCommand):
    help = 'Evaluate latest PageSpeed reports against previous reports using AI.'

    def add_arguments(self, parser):
        parser.add_argument('--website-id', type=int, help='Evaluate reports for one website only.')
        parser.add_argument('--page-id', type=int, help='Evaluate reports for one saved page only.')

    def handle(self, *args, **options):
        results = evaluate_website_latest_vs_previous(
            website_id=options.get('website_id'),
            page_id=options.get('page_id'),
        )

        completed_count = 0
        for page, evaluation, message in results:
            if evaluation and not evaluation.ai_error:
                completed_count += 1
                self.stdout.write(self.style.SUCCESS(f'{page.page_url}: {message}'))
            else:
                self.stdout.write(self.style.WARNING(f'{page.page_url}: {message}'))

        self.stdout.write(self.style.SUCCESS(f'Completed {completed_count} AI evaluation(s).'))
